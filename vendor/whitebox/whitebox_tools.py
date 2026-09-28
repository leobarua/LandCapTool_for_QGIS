#!/usr/bin/env python3
''' This file is intended to be a helper for running whitebox-tools plugins from a Python script.
See whitebox_example.py for an example of how to use it.

Trimmed from the official whitebox-tools Python API (whiteboxgeo.com) to
just the two tool calls this plugin actually uses (fill_depressions,
d8_flow_accumulation) and the shared machinery they depend on. The full
upstream file ships ~570 methods, one per WhiteboxTools CLI tool, plus
extension-install/license-registration/self-update helpers that shell out
to os.system()/urllib - none of that is reachable from this plugin, but a
security scanner auditing the full file can't tell that. See
vendor/whitebox/SETUP.md.
'''

# This script is part of the WhiteboxTools geospatial library.
# Authors: Dr. John Lindsay
# Created: 28/11/2017
# Last Modified: 09/12/2019
# License: MIT

from __future__ import print_function
import os
from os import path
import sys
import platform
import json
from subprocess import CalledProcessError, Popen, PIPE, STDOUT

running_windows = platform.system() == 'Windows'

if running_windows:
    from subprocess import STARTUPINFO, STARTF_USESHOWWINDOW

def default_callback(value):
    '''
    A simple default callback that outputs using the print function. When
    tools are called without providing a custom callback, this function
    will be used to print to standard output.
    '''
    print(value)


def to_camelcase(name):
    '''
    Convert snake_case name to CamelCase name
    '''
    return ''.join(x.title() for x in name.split('_'))


class WhiteboxTools(object):
    '''
    An object for interfacing with the WhiteboxTools executable.
    '''

    def __init__(self):
        if running_windows:
            self.ext = '.exe'
        else:
            self.ext = ''
        self.exe_name = "whitebox_tools{}".format(self.ext)
        self.exe_path = path.dirname(path.abspath(__file__))

        self.work_dir = ""
        self.verbose = True
        self.__compress_rasters = False
        self.__max_procs = -1

        if os.path.isfile('settings.json'):
            # read the settings.json file if it exists
            with open('settings.json', 'r') as settings_file:
                data = settings_file.read()

            # parse file
            settings = json.loads(data)
            self.work_dir = str(settings['working_directory'])
            self.verbose = str(settings['verbose_mode'])
            self.__compress_rasters = settings['compress_rasters']
            self.__max_procs = settings['max_procs']


        self.cancel_op = False
        self.default_callback = default_callback
        self.start_minimized = False

    def set_whitebox_dir(self, path_str):
        '''
        Sets the directory to the WhiteboxTools executable file.
        '''
        self.exe_path = path_str

    def set_working_dir(self, path_str):
        '''
        Sets the working directory, i.e. the directory in which
        the data files are located. By setting the working
        directory, tool input parameters that are files need only
        specify the file name rather than the complete file path.
        '''
        self.work_dir = path.normpath(path_str)

    def get_working_dir(self):
        return self.work_dir

    def get_verbose_mode(self):
        return self.verbose

    def run_tool(self, tool_name, args, callback=None):
        '''
        Runs a tool and specifies tool arguments.
        Returns 0 if completes without error.
        Returns 1 if error encountered (details are sent to callback).
        Returns 2 if process is cancelled by user.
        '''
        try:
            if callback is None:
                callback = self.default_callback

            os.chdir(self.exe_path)
            args2 = []
            args2.append("." + path.sep + self.exe_name)
            args2.append("--run=\"{}\"".format(to_camelcase(tool_name)))

            if self.work_dir.strip() != "":
                args2.append("--wd=\"{}\"".format(self.work_dir))

            for arg in args:
                args2.append(arg)

            if self.verbose:
                args2.append("-v")
            else:
                args2.append("-v=false")

            if self.__compress_rasters:
                args2.append("--compress_rasters=True")
            else:
                args2.append("--compress_rasters=False")

            if self.verbose:
                cl = " ".join(args2)
                callback(cl.strip() + "\n")

            proc = None

            if running_windows and self.start_minimized == True:
                si = STARTUPINFO()
                si.dwFlags = STARTF_USESHOWWINDOW
                si.wShowWindow = 7 #Set window minimized and not activated
                # nosec B603: args2 is built entirely from this file's own
                # fixed exe_name/tool-name/flag construction above, shell=False
                # (no shell metacharacter interpretation), no externally
                # controlled command string reaches Popen.
                proc = Popen(args2, shell=False, stdout=PIPE,  # nosec B603
                            stderr=STDOUT, bufsize=1, universal_newlines=True,
                            startupinfo=si)
            else:
                # nosec B603: same as above - fixed args2, shell=False.
                proc = Popen(args2, shell=False, stdout=PIPE,  # nosec B603
                            stderr=STDOUT, bufsize=1, universal_newlines=True)

            while proc is not None:
                line = proc.stdout.readline()
                sys.stdout.flush()
                if line != '':
                    if not self.cancel_op:
                        if self.verbose:
                            callback(line.strip())
                    else:
                        self.cancel_op = False
                        proc.terminate()
                        return 2
                else:
                    break

            return 0
        except (OSError, ValueError, CalledProcessError) as err:
            callback(str(err))
            return 1

    ########################################################################
    # The two tool wrappers this plugin actually calls - see module
    # docstring for why the other ~570 upstream tool wrappers aren't here.
    ########################################################################

    def d8_flow_accumulation(self, i, output, out_type="cells", log=False, clip=False, pntr=False, esri_pntr=False, callback=None):
        """Calculates a D8 flow accumulation raster from an input DEM or flow pointer.

        Keyword arguments:

        i -- Input raster DEM or D8 pointer file.
        output -- Output raster file.
        out_type -- Output type; one of 'cells' (default), 'catchment area', and 'specific contributing area'.
        log -- Optional flag to request the output be log-transformed.
        clip -- Optional flag to request clipping the display max by 1%.
        pntr -- Is the input raster a D8 flow pointer rather than a DEM?.
        esri_pntr -- Input D8 pointer uses the ESRI style scheme.
        callback -- Custom function for handling tool text outputs.
        """
        args = []
        args.append("--input='{}'".format(i))
        args.append("--output='{}'".format(output))
        args.append("--out_type={}".format(out_type))
        if log: args.append("--log")
        if clip: args.append("--clip")
        if pntr: args.append("--pntr")
        if esri_pntr: args.append("--esri_pntr")
        return self.run_tool('d8_flow_accumulation', args, callback) # returns 1 if error

    def fill_depressions(self, dem, output, fix_flats=True, flat_increment=None, max_depth=None, callback=None):
        """Fills all of the depressions in a DEM. Depression breaching should be preferred in most cases.

        Keyword arguments:

        dem -- Input raster DEM file.
        output -- Output raster file.
        fix_flats -- Optional flag indicating whether flat areas should have a small gradient applied.
        flat_increment -- Optional elevation increment applied to flat areas.
        max_depth -- Optional maximum depression depth to fill.
        callback -- Custom function for handling tool text outputs.
        """
        args = []
        args.append("--dem='{}'".format(dem))
        args.append("--output='{}'".format(output))
        if fix_flats: args.append("--fix_flats")
        if flat_increment is not None: args.append("--flat_increment='{}'".format(flat_increment))
        if max_depth is not None: args.append("--max_depth='{}'".format(max_depth))
        return self.run_tool('fill_depressions', args, callback) # returns 1 if error
