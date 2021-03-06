"""This is an implementation of psffuncs in pure Python for testing
purposes."""

from __future__ import division

import math
import numpy as np


def gaussian_moffat_psf(sigma, alpha, beta, ellipticity, eta, yctr, xctr,
                        shape):
    """Evaluate a gaussian+moffat function on a 3-d grid."""

    nw = len(sigma)
    ny, nx = shape

    output = np.zeros((nw, ny, nx), dtype=np.float64)
    for i in range(nw):
        dy = np.arange(-ny/2.0 + 0.5 - yctr[i], ny/2.0 + 0.5 - yctr[i])
        dx = np.arange(-nx/2.0 + 0.5 - xctr[i], nx/2.0 + 0.5 - xctr[i])

        # Output arrays of numpy.meshgrid() are 2-d, both with
        # shape (ny, nx).  DX, for example, gives the dx value at
        # each point in the grid.
        DX, DY = np.meshgrid(dx, dy)

        # Offsets in rotated coordinate system (DX', DY')
        #DXp = DX * math.cos(angle) - DY * math.sin(angle)
        #DYp = DX * math.sin(angle) + DY * math.cos(angle)
        DXp = DX
        DYp = DY

        # We are defining, in the Gaussian,
        # sigma_x^2 / sigma_y^2 === ellipticity
        # and in the Moffat,
        # alpha_x^2 / alpha_y^2 === ellipticity
        sigma_x = sigma[i]
        alpha_x = alpha[i]
        sigma_y = sigma_x / math.sqrt(ellipticity[i])
        alpha_y = alpha_x / math.sqrt(ellipticity[i]) 

        # Unnormalized gaussian
        G = np.exp(-(DXp**2/(2.*sigma_x**2) + DYp**2/(2.*sigma_y**2)))

        # Gaussian normalization factor
        c_g = 1. / (2. * math.pi * sigma_x * sigma_y)

        # Unnormalized Moffat
        M = (1. + DXp**2/alpha_x**2 + DYp**2/alpha_y**2)**-beta[i]

        # Moffat normalization factor
        c_m = (beta[i] - 1.) / (math.pi * alpha_x * alpha_y) 

        output[i, :, :] = (M + eta[i] * G) / (1. / c_m + eta[i] / c_g)

    return output


def gaussian_plus_moffat_psf_old(shape, xctr, yctr, ellipticity, alpha, angle):
    """Evaluate a gaussian+moffat function on a 2-d grid.

    Parameters
    ----------
    shape : 2-tuple
        (ny, nx) of output array.
    xctr, yctr : float
        Center of PSF in array coordinates. (0, 0) = centered on lower left
        pixel.
    ellipticity: float
    alpha : float
    angle : float
    Returns
    -------
    psf : 2-d array
        The shape will be (len(y), len(x))
    """

    ny, nx = shape
    alpha = abs(alpha)
    ellipticity = abs(ellipticity)

    # Correlated params
    s1 = 0.215
    s0 = 0.545
    b1 = 0.345
    b0 = 1.685
    e1 = 0.0
    e0 = 1.04

    # Moffat
    sigma = s0 + s1*alpha
    beta  = b0 + b1*alpha
    eta   = e0 + e1*alpha

    # In the next line, output arrays are 2-d, both with shape (ny, nx).
    # dx, for example, gives the dx value at each point in the grid.
    dx, dy = np.meshgrid(np.arange(nx) - xctr, np.arange(ny) - yctr)

    # Offsets in rotated coordinate system (dx', dy')
    dx_prime = dx * math.cos(angle) - dy * math.sin(angle)
    dy_prime = dx * math.sin(angle) + dy * math.cos(angle)
    r2 = dx_prime**2 + ellipticity * dy_prime**2

    # Gaussian, Moffat
    gauss = np.exp(-r2 / (2. * sigma**2))
    moffat = (1. + r2 / alpha**2)**(-beta)

    # scalars normalization
    norm_moffat = 1./math.pi * math.sqrt(ellipticity) * (beta-1.) / alpha**2
    #norm_gauss = 1./math.pi * math.sqrt(ellipticity) / (2. * eta * sigma**2)

    norm_gauss = 1./math.pi * math.sqrt(ellipticity) / (2. * sigma**2)
    norm_psf = 1. / (1./norm_moffat + eta * 1./norm_gauss)

    return norm_psf * (moffat + eta*gauss)


def psf_3d_from_params(params, wave, wave_ref, shape):
    """Create a wavelength-dependent Gaussian+Moffat PSF from given
    parameters.
    Parameters
    ----------
    params : 4-tuple
        Ellipticty and polynomial parameters in wavelength
    wave : np.ndarray (1-d)
        Wavelengths
    wave_ref : float
        Reference wavelength
    shape : 2-tuple
        (ny, nx) shape of spatial component of output array.
    Returns
    -------
    psf : 3-d array
        Shape is (nw, ny, nx) where (nw,) is the shape of wave array.
        PSF will be spatially centered in array.
    """

    relwave = wave / wave_ref - 1.
    ellipticity = params[0]
    alpha = params[1] + params[2]*relwave + params[3]*relwave**2

    nw = len(wave)
    ny, nx = shape
    xctr = (nx - 1) / 2.
    yctr = (ny - 1) / 2.
    psf = np.empty((nw, ny, nx), dtype=np.float)
    for i in range(nw):
        psf2d = gaussian_plus_moffat_psf_old(shape, xctr, yctr, ellipticity,
                                             alpha[i], 0.0)
        psf2d /= np.sum(psf2d)  # normalize array sum to 1.0.
        psf[i, :, :] = psf2d

    return psf
