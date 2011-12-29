# built-ins
import os
import argparse
import re
import json
from os.path import split as split_path, join as join_path
from fnmatch import filter as fnfilter
import logging
import json
import itertools as it

# libraries
import h5py, Image, numpy

from scipy.ndimage.measurements import label

from numpy import array, asarray, uint8, uint16, uint32, uint64, zeros, \
    zeros_like, squeeze, fromstring, ndim, concatenate, newaxis, swapaxes, \
    savetxt, unique, double, ones, ones_like, prod
import numpy as np
try:
    from numpy import imread
except ImportError:
    try:
        from matplotlib.pyplot import imread
    except:
        logging.warning('unable to load numpy.imread or matplotlib.imread')
        def imread(*args, **kwargs):
            raise RuntimeError('Function imread not imported.')

arguments = argparse.ArgumentParser(add_help=False)
arggroup = arguments.add_argument_group('Image IO options')
arggroup.add_argument('-I', '--invert-image', action='store_true',
    default=False,
    help='Invert the probabilities before segmenting.'
)
arggroup.add_argument('-m', '--median-filter', action='store_true', 
    default=False, help='Run a median filter on the input image.'
)

def tryint(s):
    try:
        return int(s)
    except ValueError:
        return s

def alphanumeric_key(s):
    """Turn a string into a list of string and number chunks.

    "z23a" --> ["z", 23, "a"]

    Copied from 
    http://stackoverflow.com/questions/4623446/how-do-you-sort-files-numerically/4623518#4623518
    on 2011-09-01
    """
    return [tryint(c) for c in re.split('([0-9]+)', s)]

supported_image_extensions = ['png', 'tif', 'tiff', 'jpg', 'jpeg']

def read_image_stack(fn, *args, **kwargs):
    """Read a 3D volume of images in image or .h5 format into a numpy.ndarray.

    The format is automatically detected from the (first) filename.

    A 'crop' keyword argument is supported, as a list of 
    [xmax, xmin, ymax, ymin, zmax, zmin]. Use 'None' for no crop in that 
    coordinate.

    If reading in .h5 format, keyword arguments are passed through to
    read_h5_stack().
    """
    d, fn = split_path(os.path.expanduser(fn))
    if len(d) == 0: d = '.'
    crop = kwargs.get('crop', [None]*6)
    if len(crop) == 4: crop.extend([None]*2)
    elif len(crop) == 2: crop = [None]*4 + crop
    kwargs['crop'] = crop
    if any([fn.endswith(ext) for ext in supported_image_extensions]):
        xmin, xmax, ymin, ymax, zmin, zmax = crop
        if len(args) > 0 and type(args[0]) == str and args[0].endswith(fn[-3:]):
            # input is a list of filenames
            fns = [fn] + [split_path(f)[1] for f in args]
        else:
            # input is a filename pattern to match
            fns = fnfilter(os.listdir(d), fn)
        if len(fns) == 1 and fns[0].endswith('.tif'):
            stack = read_multi_page_tif(join_path(d,fns[0]), crop)
        else:
            fns.sort(key=alphanumeric_key) # sort filenames numerically
            fns = fns[zmin:zmax]
            im0 = pil_to_numpy(Image.open(join_path(d,fns[0])))
            ars = (pil_to_numpy(Image.open(join_path(d,fn))) for fn in fns)
            im0 = im0[xmin:xmax,ymin:ymax]
            dtype = im0.dtype
            stack = zeros((len(fns),)+im0.shape, dtype)
            for i, im in enumerate(ars):
                stack[i] = im[xmin:xmax,ymin:ymax]
    if fn.endswith('.h5'):
        stack = read_h5_stack(join_path(d,fn), *args, **kwargs)
    return squeeze(stack)

def single_arg_read_image_stack(fn):
    """Read an image stack and print exceptions as they occur.
    
    argparse.ArgumentParser() subsumes exceptions when they occur in the 
    argument type, masking lower-level errors. This function prints out the
    error before propagating it up the stack.
    """
    try:
        return read_image_stack(fn)
    except Exception as err:
        print err
        raise

def pil_to_numpy(img):
    return array(img.getdata()).reshape((img.size[1], img.size[0]))

def read_multi_page_tif(fn, crop=[None]*6):
    """Read a multi-page tif file and return a numpy array."""
    xmin, xmax, ymin, ymax, zmin, zmax = crop
    img = Image.open(fn)
    pages = []
    if zmin is not None and zmin > 0:
        img.seek(zmin)
    eof = False
    while not eof and img.tell() != zmax:
        pages.append(pil_to_numpy(img)[...,newaxis])
        try:
            img.seek(img.tell()+1)
        except EOFError:
            eof = True
    return concatenate(pages, axis=-1)
        

shiv_typecode_to_numpy_type = {
    0:np.int8, 1:np.uint8, 2:np.int16, 3:np.uint16,
    4:np.int32, 5:np.uint32, 6:np.int64, 7:np.uint64,
    8:np.float32, 9:np.float64
}

def read_shiv_raw_stack(ws_fn, sp2body_fn):
    ws_fn, sp2body_fn = map(os.path.expanduser, [ws_fn, sp2body_fn])
    ws = read_shiv_raw_array(ws_fn)
    sp2b = read_shiv_raw_array(sp2body_fn)[1]
    ar = sp2b[ws]
    return remove_merged_boundaries(ar)

def remove_merged_boundaries(ar):
    import morpho
    arp = morpho.pad(ar, [0,ar.max()+1])
    arpr = arp.ravel()
    zero_idxs = (arpr == 0).nonzero()[0]
    ns = arpr[morpho.get_neighbor_idxs(arp, zero_idxs)]
    ns_compl = ns.copy()
    ns_compl[ns==0] = ns.max()+1
    merged_boundaries = (ns.max(axis=1) == ns_compl.min(axis=1)).nonzero()[0]
    arpr[zero_idxs[merged_boundaries]] = ns.max(axis=1)[merged_boundaries]
    return morpho.juicy_center(arp, 2)

def read_shiv_raw_array(fn):
    fin = open(fn, 'rb')
    typecode = fromstring(fin.read(4), uint8)[1]
    ar_type = shiv_typecode_to_numpy_type[typecode]
    ar_ndim = fromstring(fin.read(4), uint8)[0]
    ar_shape = fromstring(fin.read(ar_ndim*4), uint32)
    ar = fromstring(fin.read(), ar_type).reshape(ar_shape, order='F')
    return ar

numpy_type_to_vtk_string = {
    np.uint8:'unsigned_char', np.int8:'char', np.uint16:'unsigned_short',
    np.int16:'short', np.uint32:'unsigned_int', np.int32:'int',
    np.uint64:'unsigned_long', np.int64:'long', np.float32:'float',
    np.float64:'double'
}

vtk_string_to_numpy_type = \
    dict([(v,k) for k, v in numpy_type_to_vtk_string.items()])

def write_vtk(ar, fn, **kwargs):
    """Write volume to VTK structured points format file.

    Code adapted from Erik Vidholm's writeVTK.m Matlab implementation.
    """
    # write header
    f = open(fn, 'w')
    f.write('# vtk DataFile Version 3.0\n')
    f.write('created by write_vtk (Python implementation by JNI)\n')
    f.write('BINARY\n')
    f.write('DATASET STRUCTURED_POINTS\n')
    f.write(' '.join(['DIMENSIONS'] + map(str, ar.shape)) + '\n')
    f.write(' '.join(['ORIGIN'] + map(str, zeros(3))) + '\n')
    f.write(' '.join(['SPACING'] +
                            map(str, kwargs.get('spacing', ones(3)))) + '\n')
    f.write('POINT_DATA ' + str(ar.size) + '\n')
    f.write('SCALARS image_data ' +
                            numpy_type_to_vtk_string[ar.dtype.type] + '\n')
    f.write('LOOKUP_TABLE default\n');
    f.close()

    # write data as binary
    f = open(fn, 'ab')
    f.write(ar.data)
    f.close()

def read_vtk(fin, **kwargs):
    """Read a numpy volume from a VTK structured points file.

    Code adapted from Erik Vidholm's readVTK.m Matlab implementation.
    """
    f = open(fin, 'r')
    num_lines_in_header = 10
    lines = [f.readline() for i in range(num_lines_in_header)]
    shape_line = [line for line in lines if line.startswith('DIMENSIONS')][0]
    type_line = [line for line in lines 
        if line.startswith('SCALARS') or line.startswith('VECTORS')][0]
    ar_shape = map(int, shape_line.rstrip('\n').split(' ')[1:])
    ar_type = vtk_string_to_numpy_type[type_line.rstrip('\n').split(' ')[2]]
    itemsize = np.dtype(ar_type).itemsize
    ar = squeeze(fromstring(f.read(), ar_type).reshape(ar_shape+[-1]))
    return ar

def read_h5_stack(fn, *args, **kwargs):
    """Read a volume in HDF5 format into numpy.ndarray.

    Accepts keyword arguments 'group' (the group in the HDF5 file containing
    the array information; default: 'stack') and 'crop' (format as in 
    read_image_stack())
    """
    fn = os.path.expanduser(fn)
    if len(args) > 0:
        group = args[0]
    elif kwargs.has_key('group'):
        group = kwargs['group']
    else:
        group = 'stack'
    if kwargs.has_key('crop'):
        crop = kwargs['crop']
    else:
        crop = [None,None,None,None,None,None]
    xmin, xmax, ymin, ymax, zmin, zmax = crop
    dset = h5py.File(fn, 'r')
    a = dset[group]
    if ndim(a) == 2:
        a = a[xmin:xmax,ymin:ymax]
    elif ndim(a) == 3:
        a = a[xmin:xmax,ymin:ymax,zmin:zmax]
    return array(a)

def ucm_to_raveler(ucm, body_threshold=0.5, sp_threshold=0, **kwargs):
    sps = label(ucm<sp_threshold)[0]
    bodies = label(ucm<=body_threshold)[0]
    return segs_to_raveler(sps, bodies, **kwargs)

def segs_to_raveler(sps, bodies, **kwargs):
    import morpho
    min_sp_size = kwargs.get('min_sp_size', 64)
    sps_out = []
    sps_per_plane = []
    sp_to_segment = []
    segment_to_body = [array([[0,0]])]
    total_nsegs = 0
    for i, (sp_map, body_map) in enumerate(zip(sps, bodies)):
        sp_map, nsps = label(
            morpho.remove_small_connected_components(sp_map, min_sp_size, True)
        )
        segment_map, nsegs = label(body_map)
        segment_map += total_nsegs
        segment_map *= sp_map.astype(bool)
        total_nsegs += nsegs
        sps_out.append(sp_map[newaxis,...])
        sps_per_plane.append(nsps)
        valid = (sp_map != 0) + (segment_map == 0)
        sp_to_segment.append(unique(
            zip(it.repeat(i), sp_map[valid], segment_map[valid])))
        valid = segment_map != 0
        logging.debug('plane %i done'%i)
        segment_to_body.append(unique(
                                zip(segment_map[valid], body_map[valid])))
    logging.info('total superpixels before: ' + str(len(unique(sps))) +
                    'total superpixels after: ' + str(sum(sps_per_plane)))
    sps_out = concatenate(sps_out, axis=0)
    sp_to_segment = concatenate(sp_to_segment, axis=0)
    segment_to_body = concatenate(segment_to_body, axis=0)
    modified = ((sps_out == 0)*(sps != 0)).astype(bool)
    return sps_out, sp_to_segment, segment_to_body, modified

def write_to_raveler(sps, sp_to_segment, segment_to_body, modified, directory,
                                                                    gray=None):
    if not os.path.exists(directory):
        os.makedirs(directory)
    if not os.path.exists(directory+'/superpixel_maps'):
        os.mkdir(directory+'/superpixel_maps')
    write_png_image_stack(sps, 
        join_path(directory,'superpixel_maps/sp_map.%05i.png'), axis=0)
    savetxt(join_path(directory, 'superpixel_to_segment_map.txt'),
                                                        sp_to_segment, '%i') 
    savetxt(join_path(directory, 'segment_to_body_map.txt'), segment_to_body,
                                                                        '%i')
    if gray is not None:
        if not os.path.exists(directory+'/grayscale_maps'):
            os.mkdir(directory+'/grayscale_maps')
        write_png_image_stack(gray, 
                join_path(directory,'grayscale_maps/img.%05d.png'), axis=0)
    write_h5_stack(modified, join_path(directory, 'modified.h5'))

def raveler_to_labeled_volume(rav_export_dir, get_glia=False, **kwargs):
    """Import a raveler export stack into a labeled segmented volume."""
    import morpho
    spmap = read_image_stack(
        os.path.join(rav_export_dir, 'superpixel_maps', '*.png'), **kwargs)
    sp2seg_list = numpy.loadtxt(
        os.path.join(rav_export_dir, 'superpixel_to_segment_map.txt'), uint32)
    seg2bod_list = numpy.loadtxt(
        os.path.join(rav_export_dir, 'segment_to_body_map.txt'), uint32)
    sp2seg = {}
    max_sp = sp2seg_list[:,1].max()
    for z, sp, seg in sp2seg_list:
        if not sp2seg.has_key(z):
            sp2seg[z] = zeros(max_sp+1, uint32)
        sp2seg[z][sp] = seg
    max_seg = seg2bod_list[:,0].max()
    seg2bod = zeros(max_seg+1, uint32)
    seg2bod[seg2bod_list[:,0]] = seg2bod_list[:,1]
    initial_output_volume = zeros_like(spmap)
    for i, m in enumerate(spmap):
        initial_output_volume[i] = seg2bod[sp2seg[i][m]]
    probs = kwargs.get('probability_map', ones_like(spmap))
    output_volume = morpho.watershed(probs, seeds=initial_output_volume)
    if get_glia:
        annots = json.load(
            open(os.path.join(rav_export_dir, 'annotations-body.json'), 'r'))
        glia = [a['body ID'] for a in annots['data'] 
                                        if a.get('comment', None) == 'glia']
        return output_volume, glia
    else:
        return output_volume

def write_image_stack(npy_vol, fn, **kwargs):
    """Write a numpy.ndarray 3D volume to a stack of images or an HDF5 file."""
    fn = os.path.expanduser(fn)
    if fn.endswith('.png'):
        write_png_image_stack(npy_vol, fn, **kwargs)
    elif fn.endswith('.h5'):
        write_h5_stack(npy_vol, fn, **kwargs)
    elif fn.endswith('.npy'):
        write_npy_image_stack(npy_vol, fn, **kwargs)
    else:
        raise ValueError('Image format not supported: ' + fn + '\n')


def write_png_image_stack(npy_vol, fn, **kwargs):
    """Write a numpy.ndarray 3D volume to a stack of .png images.

    Only 8-bit and 16-bit single-channel images are currently supported.
    """
    import morpho
    axis = kwargs.get('axis', -1)
    bitdepth = kwargs.get('bitdepth', 16)
    npy_vol = swapaxes(npy_vol, 0, axis)
    fn = os.path.expanduser(fn)
    if 0 <= npy_vol.max() <= 1 and npy_vol.dtype == double:
        imdtype = uint16 if bitdepth == 16 else uint8
        npy_vol = ((2**bitdepth-1)*npy_vol).astype(imdtype)
    if 1 < npy_vol.max() < 256:
        mode = 'L'
        mode_base = 'L'
        npy_vol = uint8(npy_vol)
    elif 256 <= numpy.max(npy_vol) < 2**16:
        mode = 'I;16'
        mode_base = 'I'
        npy_vol = uint16(npy_vol)
    else:
        mode = 'RGBA'
        mode_base = 'RGBA'
        npy_vol = uint32(npy_vol)
    for z, pl in enumerate(npy_vol):
        im = Image.new(mode_base, pl.T.shape)
        im.fromstring(pl.tostring(), 'raw', mode)
        im.save(fn % z)

def write_h5_stack(npy_vol, fn, **kwargs):
    """Write a numpy.ndarray 3D volume to an HDF5 file.

    The following keyword arguments are supported:
    - 'group': the group into which to write the array. (default: 'stack')
    - 'compression': The type of compression. (default: None)
    - 'chunks': Chunk size in the HDF5 file. (default: None)
    """
    fn = os.path.expanduser(fn)
    if not kwargs.has_key('compression'):
        kwargs['compression'] = None
    if not kwargs.has_key('chunks'):
        kwargs['chunks'] = None
    try:
        group = kwargs['group']
        del kwargs['group']
    except KeyError:
        group = 'stack'
    fout = h5py.File(fn, 'a')
    if group in fout:
        del fout[group]
    fout.create_dataset(group, data=npy_vol, **kwargs)
    fout.close()


#######################
# Image visualization #
#######################

def show_boundary(seg):
    """Show the boundary (0-label) in a 2D segmentation (labeling)."""
    seg = seg.squeeze()
    boundary = 255*(1-seg.astype(bool)).astype(uint8)
    Image.fromarray(boundary).show()

def show_image(ar):
    """Display an image from an array."""
    Image.fromarray(ar.squeeze()).show()
