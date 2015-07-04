from __future__ import print_function, division

import copy
import logging

import numpy as np
from scipy.optimize import fmin_l_bfgs_b, fmin_bfgs, fmin
import iminuit

from .utils import yxbounds

__all__ = ["guess_sky", "fit_galaxy_single", "fit_galaxy_sky_multi",
           "fit_position_sky", "fit_position_sky_sn_multi"]


def _check_result(warnflag, msg):
    """Check result of fmin_l_bfgs_b()"""
    if warnflag == 0:
        return
    if warnflag == 1:
        raise RuntimeError("too many function calls or iterations "
                           "in fmin_l_bfgs_b()")
    if warnflag == 2:
        raise RuntimeError("fmin_l_bfgs_b() exited with warnflag=2: %s" % msg)
    raise RuntimeError("unknown warnflag: %s" % warnflag)


def _check_result_fmin(warnflag):
    """Check result of fmin()"""
    if warnflag == 0:
        return
    if warnflag == 1:
        raise RuntimeError("maximum number of function calls reached in fmin")
    if warnflag == 2:
        raise RuntimeError("maximum number of iterations reached in fmin")
    raise RuntimeError("unknown warnflag: %s" % warnflag)


def _log_result(fn, fval, niter, ncall):
    """Write the supplementary results from optimizer to the log"""
    logging.info("        success: %3d iterations, %3d calls, val=%8.2f",
                 niter, ncall, fval)


def guess_sky_clipping(cube, clip, maxiter=10):
    """Guess sky based on lower signal spaxels compatible with variance

    Parameters
    ----------
    cube : DataCube
    clip : float
        Number of standard deviations (not variances) to use as
        the clipping limit (on individual pixels).
    maxiter : int
        Maximum number of sigma-clipping interations. Default is 10.

    Returns
    -------
    sky : np.ndarray (1-d)
        Sky level for each wavelength.
    """

    nspaxels = cube.ny * cube.nx

    weight = np.copy(cube.weight)
    var = 1.0 / weight

    # Loop until mask stops changing size or until a maximum
    # number of iterations.
    avg = None
    oldmask = None
    mask = None
    for j in range(maxiter):
        oldmask = mask

        # weighted average spectrum (masked array).
        # We use a masked array because some of the wavelengths
        # may have all-zero weights for every pixel.
        # The masked array gets propagated so that `mask` is a
        # masked array of booleans!
        avg = np.ma.average(cube.data, weights=weight, axis=(1, 2))
        deviation = cube.data - avg[:, None, None]
        mask = deviation**2 > clip**2 * var

        # Break if the mask didn't change.
        if (oldmask is not None and
            (mask.data == oldmask.data).all() and
            (mask.mask == oldmask.mask).all()):
            break

        # set weights of masked pixels to zero. masked elements
        # of the mask are *not* changed.
        weight[mask] = 0.0
        var[mask] = 0.0

    # convert to normal (non-masked) array. Masked wavelengths are
    # set to zero in this process.
    return np.asarray(avg)


def guess_sky(cube, npix=10):
    """Guess sky based on lowest signal pixels at each wavelength.

    With the small field of fiew of an IFU, we have no guarantee of
    getting an accurate measurement of the real sky level; the galaxy
    might extend far past the edges of the IFU.

    Here we simply take a weighted average of the lowest `npix` pixels
    at each wavelength. This estimate will be higher than the real sky
    value (which would be lower than the lowest pixel value in the
    absence of noise), but its about the best we can do.

    Parameters
    ----------
    cube : DataCube
    npix : int

    Returns
    -------
    sky : np.ndarray (1-d)
        Sky level at each wavelength.
    """

    sky = np.zeros(cube.nw)
    for i in range(cube.nw):
        mask = cube.weight[i] > 0.
        v = cube.data[i][mask]
        vw = cube.weight[i][mask]
        k = min(npix, len(v))  # number of pixels to use.
        if k <= 0:
            # if there are no values with weight != 0, it doesn't
            # matter what the sky is because these data are never used
            # anywhere in the fit.
            sky[i] = 0.
        else:
            # sort values, average lowest k values.
            idx = np.argsort(v)
            sky[i] = np.average(v[idx][0:k], weights=vw[idx][0:k])

    return sky


def determine_sky_and_sn(galmodel, snmodel, data, weight):
    """Estimate the sky and SN level for a single epoch.

    Given a fixed galaxy and fixed SN PSF shape in the model, the
    (assumed spatially flat) sky background and SN flux are estimated.

    Parameters
    ----------
    galmodel : ndarray (3-d)
        The model, evaluated on the data grid.
    snmodel : ndarray (3-d)
        The PSF, evaluated on the data grid at the SN position.
    data : ndarray (3-d)
    weight : ndarray (3-d)

    Returns
    -------
    sky : ndarray
        1-d sky spectrum for given epoch.
    sn : ndarray
        1-d SN spectrum for given epoch.
    """

    A11 = (weight * snmodel**2).sum(axis=(1, 2))
    A12 = (-weight * snmodel).sum(axis=(1, 2))
    A21 = A12
    A22 = weight.sum(axis=(1, 2))

    denom = A11*A22 - A12*A21

    # There are some cases where we have slices with only 0
    # values and weights. Since we don't mix wavelengths in
    # this calculation, we put a dummy value for denom and
    # then put the sky and sn values to 0 at the end.
    mask = denom == 0.0
    if not np.all(A22[mask] == 0.0):
        raise ValueError("found null denom for slices with non null "
                         "weight")
    denom[mask] = 1.0

    # w2d, w2dy w2dz are used to calculate the variance using
    # var(alpha x) = alpha^2 var(x)*/
    tmp = weight * data
    wd = tmp.sum(axis=(1, 2))
    wdsn = (tmp * snmodel).sum(axis=(1, 2))
    wdgal = (tmp * galmodel).sum(axis=(1, 2))

    tmp = weight * galmodel
    wgal = tmp.sum(axis=(1, 2))
    wgalsn = (tmp * snmodel).sum(axis=(1, 2))
    wgal2 = (tmp * galmodel).sum(axis=(1, 2))

    b_sky = (wd * A11 + wdsn * A12) / denom
    c_sky = (wgal * A11 + wgalsn * A12) / denom
    b_sn = (wd * A21 + wdsn * A22) / denom
    c_sn = (wgal * A21 + wgalsn * A22) / denom

    sky = b_sky - c_sky
    sn = b_sn - c_sn

    sky[mask] = 0.0
    sn[mask] = 0.0

    return sky, sn


def chisq_galaxy_single(galaxy, data, weight, ctr, atm):
    """Chi^2 and gradient (not including regularization term) for a single
    epoch."""

    scene = atm.evaluate_galaxy(galaxy, data.shape[1:3], ctr)
    r = data - scene
    wr = weight * r
    val = np.sum(wr * r)
    grad = atm.gradient_helper(-2. * wr, data.shape[1:3], ctr)

    return val, grad


def chisq_galaxy_sky_single(galaxy, data, weight, ctr, atm):
    """Chi^2 and gradient (not including regularization term) for 
    single epoch, allowing sky to float."""

    scene = atm.evaluate_galaxy(galaxy, data.shape[1:3], ctr)
    r = data - scene

    # subtract off sky (weighted avg of residuals)
    sky = np.average(r, weights=weight, axis=(1, 2))
    r -= sky[:, None, None]

    wr = weight * r
    val = np.sum(wr * r)

    # See note in docs/gradient.tex for the (non-trivial) derivation
    # of this gradient!
    tmp = np.sum(wr, axis=(1, 2)) / np.sum(weight, axis=(1, 2))
    vtwr = weight * tmp[:, None, None]
    grad = atm.gradient_helper(-2. * (wr - vtwr), data.shape[1:3], ctr)

    return val, grad


def chisq_galaxy_sky_multi(galaxy, datas, weights, ctrs, atms):
    """Chi^2 and gradient (not including regularization term) for 
    multiple epochs, allowing sky to float."""

    val = 0.0
    grad = np.zeros_like(galaxy)
    for data, weight, ctr, atm in zip(datas, weights, ctrs, atms):
        epochval, epochgrad = chisq_galaxy_sky_single(galaxy, data, weight,
                                                      ctr, atm)
        val += epochval
        grad += epochgrad

    return val, grad


def fit_galaxy_single(galaxy0, data, weight, ctr, atm, regpenalty, factor):
    """Fit the galaxy model to a single epoch of data.

    Parameters
    ----------
    galaxy0 : ndarray (3-d)
        Initial galaxy model.
    data : ndarray (3-d)
        Sky-subtracted data.
    weight : ndarray (3-d)
    ctr : tuple
        Length 2 tuple giving y, x position of data in model coordinates.
    factor : float
        Factor used in fmin_l_bfgs_b to determine fit accuracy.
    """

    # Define objective function to minimize.
    # Returns chi^2 (including regularization term) and its gradient.
    def objective(galparams):

        # galparams is 1-d (raveled version of galaxy); reshape to 3-d.
        galaxy = galparams.reshape(galaxy0.shape)
        cval, cgrad = chisq_galaxy_single(galaxy, data, weight, ctr, atm)
        rval, rgrad = regpenalty(galaxy)
        totval = cval + rval
        logging.debug(u'\u03C7\u00B2 = %8.2f (%8.2f + %8.2f)', totval, cval, rval)

        # ravel gradient to 1-d when returning.
        return totval, np.ravel(cgrad + rgrad)

    # run minimizer
    galparams0 = np.ravel(galaxy0)  # fit parameters must be 1-d
    galparams, f, d = fmin_l_bfgs_b(objective, galparams0, factr=factor)
    _check_result(d['warnflag'], d['task'])
    _log_result("fmin_l_bfgs_b", f, d['nit'], d['funcalls'])

    return galparams.reshape(galaxy0.shape)


def fit_galaxy_sky_multi(galaxy0, datas, weights, ctrs, atms, regpenalty,
                         factor):
    """Fit the galaxy model to multiple data cubes.

    Parameters
    ----------
    galaxy0 : ndarray (3-d)
        Initial galaxy model.
    datas : list of ndarray
        Sky-subtracted data for each epoch to fit.
    """

    nepochs = len(datas)

    # Get initial chisq values for info output.
    cvals_init = []
    for data, weight, ctr, atm in zip(datas, weights, ctrs, atms):
        cval, _ = chisq_galaxy_single(galaxy0, data, weight, ctr, atm)
        cvals_init.append(cval)


    # Define objective function to minimize.
    # Returns chi^2 (including regularization term) and its gradient.
    def objective(galparams):

        # galparams is 1-d (raveled version of galaxy); reshape to 3-d.
        galaxy = galparams.reshape(galaxy0.shape)
        cval, cgrad = chisq_galaxy_sky_multi(galaxy, datas, weights,
                                             ctrs, atms)
        rval, rgrad = regpenalty(galaxy)
        rval *= nepochs
        rgrad *= nepochs

        totval = cval + rval
        logging.debug(u'\u03C7\u00B2 = %8.2f (%8.2f + %8.2f)', totval, cval, rval)

        # ravel gradient to 1-d when returning.
        return totval, np.ravel(cgrad + rgrad)

    # run minimizer
    galparams0 = np.ravel(galaxy0)  # fit parameters must be 1-d
    galparams, f, d = fmin_l_bfgs_b(objective, galparams0, factr=factor)
    _check_result(d['warnflag'], d['task'])
    _log_result("fmin_l_bfgs_b", f, d['nit'], d['funcalls'])

    galaxy = galparams.reshape(galaxy0.shape)

    # Get final chisq values.
    cvals = []
    for data, weight, ctr, atm in zip(datas, weights, ctrs, atms):
        cval, _ = chisq_galaxy_single(galaxy, data, weight, ctr, atm)
        cvals.append(cval)

    logging.info(u"        initial \u03C7\u00B2/epoch: [%s]",
                 ", ".join(["%8.2f" % v for v in cvals_init]))
    logging.info(u"        final   \u03C7\u00B2/epoch: [%s]",
                 ", ".join(["%8.2f" % v for v in cvals]))

    # get last-calculated skys, given galaxy.
    skys = []
    for data, weight, ctr, atm in zip(datas, weights, ctrs, atms):
        scene = atm.evaluate_galaxy(galaxy, data.shape[1:3], ctr)
        sky = np.average(data - scene, weights=weight, axis=(1, 2))
        skys.append(sky)

    return galaxy, skys


def fit_position_sky(galaxy, data, weight, ctr0, atm):
    """Fit data position and sky for a single epoch (fixed galaxy model).

    Parameters
    ----------
    galaxy : ndarray (3-d)
    data : ndarray (3-d)
    weight : ndarray(3-d)
    ctr0 : (float, float)
        Initial center.

    Returns
    -------
    ctr : (float, float)
        (y, x) center position.
    sky : ndarray (1-d)
        Fitted sky.
    """

    BOUND = 3. # +/- position bound in spaxels
    minbound = np.array(ctr0) - BOUND
    maxbound = np.array(ctr0) + BOUND

    gshape = galaxy.shape[1:3]  # model shape
    dshape = data.shape[1:3]

    (yminabs, ymaxabs), (xminabs, xmaxabs) = yxbounds(gshape, dshape)
    minbound[0] = max(minbound[0], yminabs)  # ymin
    maxbound[0] = min(maxbound[0], ymaxabs)  # ymax
    minbound[1] = max(minbound[1], xminabs)  # xmin
    maxbound[1] = min(maxbound[1], xmaxabs)  # xmax

    def objective_func(ctr):
        if not (minbound[0] < ctr[0] < maxbound[0] and
                minbound[1] < ctr[1] < maxbound[1]):
            return np.inf
        gal = atm.evaluate_galaxy(galaxy, dshape, ctr)

        # determine sky (linear problem)
        resid = data - gal
        sky = np.average(resid, weights=weight, axis=(1, 2))

        out = np.sum(weight * (resid - sky[:, None, None])**2)

        logging.debug("(%f, %f) %f", ctr[0], ctr[1], out)

        return out

    ctr, fval, niter, ncall, warnflag = fmin(objective_func, ctr0,
                                             full_output=1, disp=0)
    _check_result_fmin(warnflag)
    _log_result("fmin", fval, niter, ncall)

    # get last-calculated sky.
    gal = atm.evaluate_galaxy(galaxy, dshape, ctr)
    sky = np.average(data - gal, weights=weight, axis=(1, 2))

    return tuple(ctr), sky

def chisq_position_sky_sn_multi(allctrs, galaxy, datas, weights, atms):
    """Function to minimize. `allctrs` is a 1-d ndarray:

    [yctr[0], xctr[0], yctr[1], xctr[1], ..., snyctr, snxctr]

    where the indicies are
    """
    EPS = 0.001  # size of change in spaxels for gradient calculation

    nepochs = len(datas)
    allctrs = allctrs.reshape((nepochs+1, 2))
    snctr = tuple(allctrs[nepochs, :])

    # initialize return values
    grad = np.zeros_like(allctrs)
    chisq = 0.

    for i in range(nepochs):
        data = datas[i]
        weight = weights[i]
        atm = atms[i]
        ctr = tuple(allctrs[i, :])

        # calculate chisq for this epoch; add to total.
        gal = atm.evaluate_galaxy(galaxy, data.shape[1:3], ctr)
        psf = atm.evaluate_point_source(snctr, data.shape[1:3], ctr)
        sky, sn = determine_sky_and_sn(gal, psf, data, weight)
        scene = sky[:, None, None] + gal + sn[:, None, None] * psf
        epoch_chisq = np.sum(weight * (data - scene)**2)
        chisq += epoch_chisq

        # calculate change in chisq from changing the sn position,
        # in this epoch.
        for j, snctr2 in ((0, (snctr[0]+EPS, snctr[1]    )),
                          (1, (snctr[0]    , snctr[1]+EPS))):
            psf = atm.evaluate_point_source(snctr2, data.shape[1:3], ctr)
            sky, sn = determine_sky_and_sn(gal, psf, data, weight)
            scene = sky[:, None, None] + gal + sn[:, None, None] * psf
            new_epoch_chisq = np.sum(weight * (data - scene)**2)
            grad[nepochs, j] += (new_epoch_chisq - epoch_chisq) / EPS

        # calculate change in chisq from changing the data position for
        # this epoch.
        for j, ctr2 in ((0, (ctr[0]+EPS, ctr[1]    )),
                        (1, (ctr[0]    , ctr[1]+EPS))):
            gal = atm.evaluate_galaxy(galaxy, data.shape[1:3], ctr2)
            psf = atm.evaluate_point_source(snctr, data.shape[1:3], ctr2)
            sky, sn = determine_sky_and_sn(gal, psf, data, weight)
            scene = sky[:, None, None] + gal + sn[:, None, None] * psf
            new_epoch_chisq = np.sum(weight * (data - scene)**2)
            grad[i, j] = (new_epoch_chisq - epoch_chisq) / EPS

    # reshape gradient to 1-d upon return.
    return chisq, np.ravel(grad)

def fit_position_sky_sn_multi(galaxy, datas, weights, ctrs0, snctr0, atms):
    """Fit data pointing (nepochs), SN position (in model frame),
    SN amplitude (nepochs), and sky level (nepochs). This is meant to be
    used only on epochs with SN light.

    Parameters
    ----------
    galaxy : ndarray (3-d)
    datas : list of ndarray (3-d)
    weights : list of ndarray (3-d)
    ctrs0 : list of tuples
        Initial data positions (y, x)
    snctr0 : tuple
        Initial SN position.
    atms : list of AtmModels

    Returns
    -------
    fctrs : list of tuples
        Fitted data positions.
    fsnctr : tuple
        Fitted SN position.
    skys : list of ndarray (1-d)
        FItted sky spectra for each epoch.
    sne : list of ndarray (1-d)
        Fitted SN spectra for each epoch.

    Notes
    -----
    Given the data pointing and SN position, determining
    the sky level and SN amplitude is a linear problem. Therefore, we
    have only the data pointing and sn position as parameters in the
    (nonlinear) optimization and determine the sky and sn amplitude in
    each iteration.
    """

    BOUND = 2. # +/- position bound in spaxels

    nepochs = len(datas)
    assert len(weights) == len(ctrs0) == len(atms) == nepochs

    # Initial parameter array. Has order [y0, x0, y1, x1, ... , ysn, xsn].
    allctrs0 = np.ravel(np.vstack((ctrs0, snctr0)))

    # Default parameter bounds for all parameters.
    minbound = allctrs0 - BOUND
    maxbound = allctrs0 + BOUND

    # For data position parameters, check that bounds do not extend
    # past the edge of the model and adjust the minbound and maxbound.
    # For SN position bounds, we don't do any checking like this.
    gshape = galaxy.shape[1:3]  # model shape
    for i in range(nepochs):
        dshape = datas[i].shape[1:3]
        (yminabs, ymaxabs), (xminabs, xmaxabs) = yxbounds(gshape, dshape)
        minbound[2*i] = max(minbound[2*i], yminabs)  # ymin
        maxbound[2*i] = min(maxbound[2*i], ymaxabs)  # ymax
        minbound[2*i+1] = max(minbound[2*i+1], xminabs)  # xmin
        maxbound[2*i+1] = min(maxbound[2*i+1], xmaxabs)  # xmax

    bounds = zip(minbound, maxbound)  # [(y0min, y0max), (x0min, x0max), ...]

    def objective_func(*allctrs):

        allctrs = np.array(allctrs)
        if (allctrs < minbound).any() or (allctrs > maxbound).any():
            return np.inf
        chisq, grad = chisq_position_sky_sn_multi(allctrs, galaxy, datas,
                                                  weights, atms)
        return chisq


    def callback(params):
        for i in range(len(params)//2-1):
            logging.debug('Epoch %s: %s, %s', i, params[2*i], params[2*i+1])
        logging.debug('SN position %s, %s', params[-2], params[-1])

    #logging.debug('Bounds:')
    # this was wrong
    #logging.debug('')
    
    # iminuit version
    # -------------------------------------------------------
    param_names = []
    for i in range(len(datas)):
        param_names.extend(("y%d" % i, "x%d" % i))
    param_names.extend(("ysn", "xsn"))

    # initial values, step sizes, and bounds
    kwargs = {}
    for i, name in enumerate(param_names):
        kwargs[name] = allctrs0[i]
        kwargs["error_" + name] = 0.01
        kwargs["limit_" + name] = bounds[i]

    logging.debug("Initial position parameters:")
    for name in param_names:
        logging.debug("        %s : %7.4f [%7.4f, %7.4f]", name, kwargs[name],
                      kwargs["limit_" + name][0], kwargs["limit_" + name][1])

    verbose = True
    m = iminuit.Minuit(objective_func, errordef=1.,
                       forced_parameters=param_names,
                       print_level=(1 if verbose else 0),
                       throw_nan=True, **kwargs)
    d, l = m.migrad(ncall=10000)

    # Build a message.
    message = []
    if d.has_reached_call_limit:
        message.append('Reached call limit.')
    if d.hesse_failed:
        message.append('Hesse Failed.')
    if not d.has_covariance:
        message.append('No covariance.')
    elif not d.has_accurate_covar:  # iminuit docs wrong
        message.append('Covariance may not be accurate.')
    if not d.has_posdef_covar:  # iminuit docs wrong
        message.append('Covariance not positive definite.')
    if d.has_made_posdef_covar:
        message.append('Covariance forced positive definite.')
    if not d.has_valid_parameters:
        message.append('Parameter(s) value and/or error invalid.')
    if len(message) == 0:
        message.append('Minimization exited successfully.')
        # iminuit: m.np_matrix() doesn't work

    # numpy array of best-fit values
    fallctrs = np.array([m.values[name] for name in param_names])
    logging.debug("Final position parameters:")
    for name in param_names:
        logging.debug("        %s : %7.4f [%7.4f, %7.4f]", name, m.values[name],
                      kwargs["limit_" + name][0], kwargs["limit_" + name][1])


    #fallctrs, fval, niter, ncall, warnflag = fmin(objective_func, allctrs0,
    #                                              full_output=1, disp=0)
    #_check_result_fmin(warnflag)
    #_log_result("fmin", fval, niter, ncall)


    #fallctrs, f, d = fmin_l_bfgs_b(chisq_position_sky_sn_multi, allctrs0,
    #                               args=(galaxy, datas, weights, atms),
    #                               iprint=0, callback=callback, bounds=bounds)
    #_check_result(d['warnflag'], d['task'])
    #_log_result("fmin_l_bfgs_b", f, d['nit'], d['funcalls'])

    # pull out fitted positions
    fallctrs = fallctrs.reshape((nepochs+1, 2))
    fsnctr = tuple(fallctrs[nepochs, :])
    fctrs = [tuple(fallctrs[i, :]) for i in range(nepochs)]

    # evaluate final sky and sn in each epoch
    skys = []
    sne = []
    for i in range(nepochs):
        gal = atms[i].evaluate_galaxy(galaxy, datas[i].shape[1:3], fctrs[i])
        psf = atms[i].evaluate_point_source(fsnctr, datas[i].shape[1:3],
                                            fctrs[i])
        sky, sn = determine_sky_and_sn(gal, psf, datas[i], weights[i])
        skys.append(sky)
        sne.append(sn)

    return fctrs, fsnctr, skys, sne
