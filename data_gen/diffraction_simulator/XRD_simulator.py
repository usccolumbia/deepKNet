# coding: utf-8
# Copyright (c) Pymatgen Development Team.
# Distributed under the terms of the MIT License.

__author__ = "Shyue Ping Ong"
__copyright__ = "Copyright 2012, The Materials Project"
__version__ = "0.1"
__maintainer__ = "Shyue Ping Ong"
__email__ = "ongsp@ucsd.edu"
__date__ = "5/22/14"

"""
This module implements an XRD pattern calculator.
Modified for deepKNet point cloud model
"""

import os
import json
import math
import numpy as np
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer
from pymatgen.analysis.diffraction.core import AbstractDiffractionPatternCalculator,\
                                               DiffractionPattern, get_unique_families

# XRD wavelengths in angstroms
WAVELENGTHS = {
    "CrKa2": 2.29361,
    "CrKa" : 2.29100,
    "CrKa1": 2.28970,
    "CrKb1": 2.08487,
    "FeKa2": 1.93998,
    "FeKa" : 1.93735,
    "FeKa1": 1.93604,
    "CoKa2": 1.79285,
    "CoKa" : 1.79026,
    "CoKa1": 1.78896,
    "FeKb1": 1.75661,
    "CoKb1": 1.63079,
    "CuKa2": 1.54439,
    "CuKa" : 1.54184,
    "CuKa1": 1.54056,
    "CuKb1": 1.39222,
    "mywave": 1.0000,
    "MoKa2": 0.71359,
    "MoKa" : 0.71073,
    "MoKa1": 0.70930,
    "MoKb1": 0.63229,
    "AgKa2": 0.563813,
    "AgKa" : 0.560885,
    "AgKa1": 0.559421,
    "AgKb1": 0.497082,
}

with open(os.path.join(os.path.dirname(__file__),
                       "atomic_scattering_params.json")) as f:
    ATOMIC_SCATTERING_PARAMS = json.load(f)

class XRDSimulator(AbstractDiffractionPatternCalculator):
    """
    Computes the XRD pattern of a crystal structure.

    This code is implemented by Shyue Ping Ong as part of UCSD's NANO106 -
    Crystallography of Materials. The formalism for this code is based on
    that given in Chapters 11 and 12 of Structure of Materials by Marc De
    Graef and Michael E. McHenry. This takes into account the atomic
    scattering factors and the Lorentz polarization factor, but not
    the Debye-Waller (temperature) factor (for which data is typically not
    available). Note that the multiplicity correction is not needed since
    this code simply goes through all reciprocal points within the limiting
    sphere, which includes all symmetrically equivalent facets. The algorithm
    is as follows

    1. Calculate reciprocal lattice of structure. Find all reciprocal points
       within the limiting sphere given by :math:`\\frac{2}{\\lambda}`.

    2. For each reciprocal point :math:`\\mathbf{g_{hkl}}` corresponding to
       lattice plane :math:`(hkl)`, compute the Bragg condition
       :math:`\\sin(\\theta) = \\frac{\\lambda}{2d_{hkl}}`

    3. Compute the structure factor as the sum of the atomic scattering
       factors. The atomic scattering factors are given by

       .. math::

           f(s) = Z - 41.78214 \\times s^2 \\times \\sum\\limits_{i=1}^n a_i \
           \\exp(-b_is^2)

       where :math:`s = \\frac{\\sin(\\theta)}{\\lambda}` and :math:`a_i`
       and :math:`b_i` are the fitted parameters for each element. The
       structure factor is then given by

       .. math::

           F_{hkl} = \\sum\\limits_{j=1}^N f_j \\exp(2\\pi i \\mathbf{g_{hkl}}
           \\cdot \\mathbf{r})

    4. The intensity is then given by the modulus square of the structure
       factor.

       .. math::

           I_{hkl} = F_{hkl}F_{hkl}^*

    5. Finally, the Lorentz polarization correction factor is applied. This
       factor is given by:

       .. math::

           P(\\theta) = \\frac{1 + \\cos^2(2\\theta)}
           {\\sin^2(\\theta)\\cos(\\theta)}
    """

    def __init__(self, wavelength="CuKa", symprec=0):
        """
        Initializes the XRD calculator with a given radiation.

        Args:
            wavelength (str/float): The wavelength can be specified as either a
                float or a string. If it is a string, it must be one of the
                supported definitions in the AVAILABLE_RADIATION class
                variable, which provides useful commonly used wavelengths.
                If it is a float, it is interpreted as a wavelength in
                angstroms. Defaults to "CuKa", i.e, Cu K_alpha radiation.
            symprec (float): Symmetry precision for structure refinement. If
                set to 0, no refinement is done. Otherwise, refinement is
                performed using spglib with provided precision.
        """
        if isinstance(wavelength, float):
            self.wavelength = wavelength
        else:
            self.wavelength = WAVELENGTHS[wavelength]
        self.symprec = symprec

    def get_pattern(self, structure, scale_intensity=True, two_theta_range=None):
        """
        Calculates the diffraction pattern for a structure.

        Args:
            structure (Structure): Input structure
            scale_intensity (bool): Whether to return scaled intensities. The maximum
                peak is set to a value of 100. Defaults to True. Use False if
                you need the absolute values to combine XRD plots.
            two_theta_range ([float of length 2]): Tuple for range of
                two_thetas to calculate in degrees. Defaults to (0, 90). Set to
                None if you want all diffracted beams within the limiting
                sphere of radius 2 / wavelength.

        Returns:
            XRDPattern,
            list of features for point cloud representation,
            recip_latt
        """
        try:
            assert(self.symprec == 0)
        except:
            print('symprec is not zero, terminate the process and check your input..')
        if self.symprec:
            finder = SpacegroupAnalyzer(structure, symprec=self.symprec)
            structure = finder.get_refined_structure()

        latt = structure.lattice
        volume = structure.volume
        is_hex = latt.is_hexagonal()

        # Obtained from Bragg condition. Note that reciprocal lattice
        # vector length is 1 / d_hkl.
        try:
            assert(two_theta_range == None)
        except:
            print('two theta range is not None, terminate the process and check your input..')
        min_r, max_r = (0., 2. / self.wavelength) if two_theta_range is None else \
            [2 * math.sin(math.radians(t / 2)) / self.wavelength for t in two_theta_range]

        # Obtain crystallographic reciprocal lattice points within range
        # recip_pts entry: [coord, distance, index, image]
        recip_latt = latt.reciprocal_lattice_crystallographic
        recip_pts = recip_latt.get_points_in_sphere(
            [[0, 0, 0]], [0, 0, 0], max_r)
        if min_r:
            recip_pts = [pt for pt in recip_pts if pt[1] >= min_r]
        
        # Create a flattened array of zs, coeffs, fcoords and occus. This is
        # used to perform vectorized computation of atomic scattering factors
        # later. Note that these are not necessarily the same size as the
        # structure as each partially occupied specie occupies its own
        # position in the flattened array.
        zs = []
        coeffs = []
        fcoords = []
        occus = []

        for site in structure:
            # do not consider mixed species at the same site
            try:
                assert(len(site.species.items()) == 1)
            except:
                print('mixed species at the same site detected, abort..')
            for sp, occu in site.species.items():
                zs.append(sp.Z)
                try:
                    c = ATOMIC_SCATTERING_PARAMS[sp.symbol]
                except KeyError:
                    raise ValueError("Unable to calculate XRD pattern as "
                                     "there is no scattering coefficients for"
                                     " %s." % sp.symbol)
                coeffs.append(c)
                fcoords.append(site.frac_coords)
                occus.append(occu)

        zs = np.array(zs)
        coeffs = np.array(coeffs)
        fcoords = np.array(fcoords)
        occus = np.array(occus)
        try:
            assert(np.max(occus) == np.min(occus) == 1) # all sites should be singly occupied
        except:
            print('check occupancy values...')
        peaks = {}
        two_thetas = []

        total_electrons = sum(zs)
        features = [[0, 0, 0, float(total_electrons/volume)**2]]
        for hkl, g_hkl, _, _ in sorted(recip_pts,
                                       key=lambda i: (i[1], -i[0][0], -i[0][1], -i[0][2])):
            
            # skip origin and points on the limiting sphere to avoid precision problems
            if (g_hkl < 1e-4) or (g_hkl > 2./self.wavelength): continue

            d_hkl = 1. / g_hkl

            # Bragg condition
            theta = math.asin(self.wavelength * g_hkl / 2)

            # s = sin(theta) / wavelength = 1 / 2d = |ghkl| / 2 (d =
            # 1/|ghkl|)
            s = g_hkl / 2

            # Store s^2 since we are using it a few times.
            s2 = s ** 2

            # Vectorized computation of g.r for all fractional coords and
            # hkl. Output size is N_atom
            g_dot_r = np.dot(fcoords, np.transpose([hkl])).T[0]

            # Highly vectorized computation of atomic scattering factors.
            # Equivalent non-vectorized code is::
            #
            #   for site in structure:
            #      el = site.specie
            #      coeff = ATOMIC_SCATTERING_PARAMS[el.symbol]
            #      fs = el.Z - 41.78214 * s2 * sum(
            #          [d[0] * exp(-d[1] * s2) for d in coeff])
            fs = zs - 41.78214 * s2 * np.sum(
                coeffs[:, :, 0] * np.exp(-coeffs[:, :, 1] * s2), axis=1)
            
            # Structure factor = sum of atomic scattering factors (with
            # position factor exp(2j * pi * g.r and occupancies).
            # Vectorized computation.
            f_hkl = np.sum(fs * occus * np.exp(2j * math.pi * g_dot_r))

            # Lorentz polarization correction for hkl
            lorentz_factor = (1 + math.cos(2 * theta) ** 2) / \
                (math.sin(theta) ** 2 * math.cos(theta))

            # Intensity for hkl is modulus square of structure factor.
            i_hkl = (f_hkl * f_hkl.conjugate()).real
            try:
                assert(i_hkl < total_electrons**2)
            except:
                print('assertion failed, check I_hkl values..')
            i_hkl_out = i_hkl / volume**2
            
            # add to features 
            features.append([hkl[0], hkl[1], hkl[2], i_hkl_out])

            ### for diffractin pattern plotting only
            two_theta = math.degrees(2 * theta)
            if is_hex:
                # Use Miller-Bravais indices for hexagonal lattices.
                hkl = (hkl[0], hkl[1], - hkl[0] - hkl[1], hkl[2])
            # Deal with floating point precision issues.
            ind = np.where(np.abs(np.subtract(two_thetas, two_theta)) <
                           AbstractDiffractionPatternCalculator.TWO_THETA_TOL)
            if len(ind[0]) > 0:
                peaks[two_thetas[ind[0][0]]][0] += i_hkl * lorentz_factor
                peaks[two_thetas[ind[0][0]]][1].append(tuple(hkl))
            else:
                peaks[two_theta] = [i_hkl * lorentz_factor, [tuple(hkl)],
                                    d_hkl]
                two_thetas.append(two_theta)

        # Scale intensities so that the max intensity is 100.
        max_intensity = max([v[0] for v in peaks.values()])
        x = []
        y = []
        hkls = []
        d_hkls = []
        for k in sorted(peaks.keys()):
            v = peaks[k]
            fam = get_unique_families(v[1])
            if v[0] / max_intensity * 100 > AbstractDiffractionPatternCalculator.SCALED_INTENSITY_TOL:
                x.append(k)
                y.append(v[0])
                hkls.append([{"hkl": hkl, "multiplicity": mult}
                             for hkl, mult in fam.items()])
                d_hkls.append(v[2])
        xrd = DiffractionPattern(x, y, hkls, d_hkls)
        if scale_intensity:
            xrd.normalize(mode="max", value=100)

        return xrd, recip_latt.matrix, features


"""
  implemented for debugging purpose
"""
import pandas as pd
from pymatgen.core.structure import Structure
from pymatgen.analysis.diffraction.xrd import XRDCalculator
if __name__ == "__main__":
    # obtain material cif file
    filenames = pd.read_csv('../MPdata_all/MPdata_all.csv', sep=';', header=0, index_col=None)['material_id']
    for ifile in filenames.sample(n=500):
        cif_file = '../MPdata_all/' + ifile + '.cif'
        assert(os.path.isfile(cif_file))
        struct = Structure.from_file(cif_file)
        sga = SpacegroupAnalyzer(struct, symprec=0.1)
        conventional_struct = sga.get_conventional_standard_structure()
    
        # compute XRD diffraction pattern and compare outputs
        pattern, _, _ = XRDSimulator('CuKa').get_pattern(conventional_struct, two_theta_range=None)
        pattern_pymatgen = XRDCalculator('CuKa').get_pattern(conventional_struct, two_theta_range=None) 
        abs_error = max(abs(np.array(pattern.x) - np.array(pattern_pymatgen.x)))
        if abs_error > 1E-12:
            print('{} did not pass the test, error: {:.6f}'.format(ifile, abs_error))
    print('finished checking the implementation..')


