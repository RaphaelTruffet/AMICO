from __future__ import absolute_import, division, print_function

import numpy as np
from re import match as re_match
from amico.util import LOG, NOTE, WARNING, ERROR

class Scheme :
    """A class to hold information about an acquisition scheme.

    The scheme can be specified in two formats:
    - as a Nx4 matrix: the first three columns are the gradient directions and
      the fourth is the b-value (s/mm^2).
    - as a Nx7 matrix: the first three columns are the gradient directions, and
      the remaining four are: the gradient strength (T/m), big delta (s),
      small delta (s) and echo time (s), respectively.

    The "Camino header line" (eg. VERSION: BVECTOR) is optional.
    """

    def __init__( self, data, b0_thr = 0 ) :
        """Initialize the acquisition scheme.

        Parameters
        ----------
        data : string or numpy.ndarray
            The filename of the scheme or a matrix containing the actual values
        b0_thr : float
            The threshold on the b-values to identify the b0 images (default: 0)
        """
        if type(data) is str :
            # try loading from file
            try :
                n = 0 # headers lines to skip to get to the numeric data
                with open(data) as fid :
                    for line in fid :
                        if re_match( r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?', line.strip() ) :
                            break
                        n += 1

                tmp = np.loadtxt( data, skiprows=n )

            except :
                ERROR( 'Unable to open scheme file' )

            self.load_from_table( tmp, b0_thr )
        else :
            # try loading from matrix
            self.load_from_table( data, b0_thr )


    def load_from_table( self, data, b0_thr = 0 ) :
        """Build the structure from an input matrix.

        The first three columns represent the gradient directions.
        Then, we accept two formats to describe each gradient:
            - if the shape of data is Nx4, the 4^ column is the b-value;
            - if the shape of data is Nx7, the last 4 columns are, respectively, the gradient strength, big delta, small delta and TE.
            - if the shape of data is Nx(4+n), the 4^ column is the time echo (TE), and the last n column are the effective gradient values beween t=0 and t=TE

        Parameters
        ----------
        data : numpy.ndarray
            Matrix containing tall the values.
        b0_thr : float
            The threshold on the b-values to identify the b0 images (default: 0)
        """
        if data.ndim == 1 :
            data = np.expand_dims( data, axis=0 )
        self.raw = data


        # number of samples
        # self.nS = self.raw.shape[0] JL: incomplete getter/setter incompatible with 3.6; this is never used any as getter always returns derived value

        # set/calculate the b-values
        if self.raw.shape[1] == 4 :
            self.version = 0
            self.b = self.raw[:,3]
        elif self.raw.shape[1] == 7 :
            self.version = 1
            self.b = ( 267.513e6 * self.raw[:,3] * self.raw[:,5] )**2 * (self.raw[:,4] - self.raw[:,5]/3.0) * 1e-6 # in mm^2/s
        elif self.raw.shape[1] > 7:
            self.version = 2
            self.b = np.array([self.compute1D_b(self.raw[i, 4:], self.raw[i, 3]) for i in range(self.raw.shape[0])])
        else :
            ERROR( 'Unrecognized scheme format' )

        # store information about the volumes
        self.b0_thr    = b0_thr
        self.b0_idx    = np.where( self.b <= b0_thr )[0]
        self.b0_count  = len( self.b0_idx )
        self.dwi_idx   = np.where( self.b > b0_thr )[0]
        self.dwi_count = len( self.dwi_idx )

        # ensure the directions are in the spherical range [0,180]x[0,180]
        idx = np.where( self.raw[:,1] < 0 )[0]
        self.raw[idx,0:3] = -self.raw[idx,0:3]

        # store information about each shell in a dictionary
        self.shells = []

        tmp = np.ascontiguousarray( self.raw[:,3:] )
        schemeUnique, schemeUniqueInd = np.unique( tmp.view([('', tmp.dtype)]*tmp.shape[1]), return_index=True )
        schemeUnique = schemeUnique.view(tmp.dtype).reshape((schemeUnique.shape[0], tmp.shape[1]))
        schemeUnique = [tmp[index] for index in sorted(schemeUniqueInd)]
        bUnique = [self.b[index] for index in sorted(schemeUniqueInd)]
        for i in range(len(schemeUnique)) :
            if bUnique[i] <= b0_thr :
                continue
            shell = {}
            shell['b'] = bUnique[i]
            if self.version == 0 :
                shell['G']     = None
                shell['Delta'] = None
                shell['delta'] = None
                shell['TE']    = None
                shell['wf']    = None
            elif self.version == 1 :
                shell['G']     = schemeUnique[i][0]
                shell['Delta'] = schemeUnique[i][1]
                shell['delta'] = schemeUnique[i][2]
                shell['TE']    = schemeUnique[i][3]
                shell['wf']    = None
            else :
                shell['G']     = None
                shell['Delta'] = None
                shell['delta'] = None
                shell['TE']    = schemeUnique[i][0]
                shell['wf']    = schemeUnique[i][1:]
            shell['idx']  = np.where((tmp == schemeUnique[i]).all(axis=1))[0]
            shell['grad'] = self.raw[shell['idx'],0:3]
            self.shells.append( shell )

    def write_Camino_wf(self, nb_steps, TE, Gx, Gy, Gz, schemefile):
        dt = TE/nb_steps
        schemefile.write(str(nb_steps)+' '+str(dt)+' ')
        nb_dec = 5
        for i in range(nb_steps):
            schemefile.write(str(round(Gx[i], nb_dec))+' ')
            schemefile.write(str(round(Gy[i], nb_dec))+' ')
            schemefile.write(str(round(Gz[i], nb_dec))+' ')
        schemefile.write('\n')

    def write_Camino_schemefile(self, schemefile_path):
        if self.version == 1:
            np.savetxt( schemefile_path, self.raw, fmt='%15.8e', delimiter=' ', header='VERSION: STEJSKALTANNER', comments='' )
        elif self.version == 2:
            schemefile = open(schemefile_path, 'w')
            schemefile.write('VERSION: GRADIENT_WAVEFORM \n')
            for i in range(self.raw.shape[0]):
                g1D = self.raw[i,4:]
                x = self.raw[i,0]
                y = self.raw[i,1]
                z = self.raw[i,2]
                TE = self.raw[i,3]
                nb_steps = len(g1D)
                self.write_Camino_wf(nb_steps, TE, x*g1D, y*g1D, z*g1D, schemefile)
            schemefile.close()

    def to_version_1(self):
        if self.version == 1 :
            return(self)
        elif self.version == 2:
            gamma = 267.513e6
            delta = 0.010
            Delta = 0.025
            gMax = [np.sqrt(value/(gamma*gamma*delta*delta*(Delta-delta/3))) for value in self.b]
            gMax = np.array(gMax)
            dataBis = np.zeros((self.raw.shape[0],7))
            dataBis[:,:3] = self.raw[:,:3]
            dataBis[:,3] = gMax
            dataBis[:,4] = Delta
            dataBis[:,5] = delta
            dataBis[:,6] = self.raw[:,3]
            return(Scheme(dataBis))

    @property
    def nS( self ) :
        return self.b0_count + self.dwi_count

    def compute1D_b(self, g, TE=0.100, unit='usual'):
        """
        Computes b value for the waveform g. Works olnly for version = 2.
        
        Parameters
        ----------
        g : numpy.ndarray
            Gradient waveform
        TE : float
            echo time (s)
        Returns
        -------
        b : float
            A matrix containing the b-value for each gradient
        """
        dt = TE/len(g)
        gamma = 2.6751987E8
        g = np.array(g)
        q = g.cumsum() * dt * gamma
        b = np.dot(q, q.T) * dt
        if unit=='usual':
            return(b/1000000)
        elif unit=='SI':
            return(b)
        else:
            return(b)
