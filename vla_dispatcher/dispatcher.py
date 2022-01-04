#!/usr/bin/env python2.7
#
# VLA DISPATCHER.
#
# Reads MCAF stream from VLA and sends position and timing commands to
# experiments who wish to coordinate observing with the VLA.
#
# Currently reads all info from the multicast OBSDOC
#
# Sarah Burke Spolaor Sep 2015
# modified Frank Schinzel Jan 05 2017 to adapt for LWA-VLA
#
#
"""
Still to do;
 1. Hook up to LWA comms software.
 2. Deal with scan duration (input line?).
 3. Correct triggering; only trigger at first scan of SB?
"""


import datetime
import os
import asyncore
import logging
from time import gmtime,strftime
from optparse import OptionParser
from collections import namedtuple

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

import mcaf_library

# GLOBAL VARIABLES
workdir = os.getcwd() # assuming we start in workdir
dispatched = {}       # Keep global list of dispatched commands
last_scan = {}
MJD_OFFSET = 2400000.5 # Offset in days between standard Julian day and MJD


ScanInfo = namedtuple('ScanInfo', ['time', 'ra', 'dec', 'intent', 'id', 'source'])


class FRBController(object):
    """
    Listens for OBS packets and tells FRB processing about any
    notable scans.
    """
    
    def __init__(self, intent='', project='', dispatch=False, verbose=False):
        # Mode can be project, intent
        self.intent = intent
        self.project = project
        self.dispatch = dispatch
        self.verbose = verbose
        
    def add_obsdoc(self, obsdoc):
        config = mcaf_library.MCAST_Config(obsdoc=obsdoc)

        # Add last entry
        if self.project == '' or self.project == config.projectID:
            try:
                logger.info(last_scan[config.projectID])
            except:
                logger.info(config.projectID)
                
            do_dispatch = False
            # check that we have already scan information in last_scan
            if config.projectID in list(last_scan.keys()):
                if self.intent == last_scan[config.projectID].intent:
                    eventType = 'ELWA_SESSION'
                    eventTime = last_scan[config.projectID].time
                    eventRA   = last_scan[config.projectID].ra
                    eventDec  = last_scan[config.projectID].dec
                    eventDur  = mcaf_library.utcjd_to_unix(config.startTime+MJD_OFFSET) - eventTime  - 30.0 # subtract expected delay 
                    eventIntent = last_scan[config.projectID].intent
                    eventID   = last_scan[config.projectID].id
                    if eventDur >= 0:
                        do_dispatch = True
                        logger.info("Will dispatch %s for position %s %s" % (config.projectID,
                                                                             eventRA,
                                                                             eventDec))
                    else:
                        logger.info("Duration: %s" % eventDur)
                        
            elif config.scan == 1:
                logger.info("*** First scan %d (%s, %s)." % (config.scan, config.scan_intent, config.projectID))
                eventType = 'ELWA_READY'
                eventTime = mcaf_library.utcjd_to_unix(config.startTime+MJD_OFFSET)
                eventRA = -1
                eventDec = -1
                eventDur = -1
                eventIntent = config.scan_intent
                eventID = int(strftime("%y%m%d%H%M",gmtime()))
                do_dispatch = True

            elif config.source == "FINISH" and last_scan[config.projectID].source == "FINISH":
                logger.info("*** Project %s has finished (source=%s)" % (config.projectID,
                                                                         config.source))
                
            else:
                logger.info("*** Skipping scan no intent match: %d (%s, %s)!" % (config.scan,
                                                                                 config.scan_intent,
                                                                                 config.projectID))
                
        else:
            logger.info("*** Skipping scan no project match: %d (%s, %s)." % (config.scan,
                                                                              config.scan_intent,
                                                                              config.projectID))
            
        if self.dispatch and do_dispatch:
            # Wait until last command disappears (i.e. cmd file is deleted by server)
            cmdfile = 'incoming.cmd'
            if os.path.exists(cmdfile):
                logger.info("Waiting for cmd queue to clear...")
            while os.path.exists(cmdfile):
                time.sleep(1)
                
            # Enqueue command
            if eventDur > 0:
                logger.info("Dispatching SESSION command for obs serial# %s." % eventID)
            else:
                logger.info("Dispatching READY command for obs serial# %s." % eventID)
            with open(cmdfile, 'w') as fh:
                fh.write("%s %i %f %f %f %f" % (eventType, eventID, eventTime, eventRA, eventDec, eventDur))
            logger.info("Done, wrote %i bytes.\n" % os.path.getsize(cmdfile))
            
        # add or update last scan
        eventTime = mcaf_library.utcjd_to_unix(config.startTime+MJD_OFFSET)
        eventRA   = config.ra_deg
        eventDec  = config.dec_deg
        eventIntent = config.scan_intent
        eventID = int(strftime("%y%m%d%H%M", gmtime()))
        eventSource = config.source
        last_scan[config.projectID] = ScanInfo(time=eventTime,
                                               ra=eventRA, dec=eventDec,
                                               intent=eventIntent,
                                               id=eventID, source=eventSource)
        
        if config.source == "FINISH":
            logger.info("*** Project %s finish scan (source=%s)" % (config.projectID,
                                                                    config.source))
            # Remove last_scan information when observation finishes
            del last_scan[config.projectID]
        else:
            logger.info("*** Scan %d (%s) contains desired project (%s=%s)." % (config.scan,
                                                                                config.scan_intent,
                                                                                config.projectID,
                                                                                self.project))
            logger.info("*** Position of source %s is (%s , %s) and start time (%s; unixtime %s)." % (config.source,
                                                                                                      config.ra_str,
                                                                                                      config.dec_str,
                                                                                                      str(config.startTime),
                                                                                                      str(mcaf_library.utcjd_to_unix(config.startTime+MJD_OFFSET))))
            

def monitor(intent, project, dispatch, verbose):
    """ Monitor of mcaf observation files. 
    Scans that match intent and project are searched (unless --dispatch).
    Blocking function.
    """

    # Set up verbosity level for log
    if verbose:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
        
    # Report start-up information
    logger.info('* * * * * * * * * * * * * * * * * * * * *')
    logger.info('* * * VLA Dispatcher is now running * * *')
    logger.info('* * * * * * * * * * * * * * * * * * * * *')
    logger.info('*   Looking for intent = %s, project = %s' % (intent, project))
    logger.debug('*   Running in verbose mode')
    if dispatch:
        logger.info('*   Running in dispatch mode. Will dispatch obs commands.')
    else:
        logger.info('*   Running in listening mode. Will not dispatch obs commands.')
    logger.info('* * * * * * * * * * * * * * * * * * * * *\n')
    
    # This starts the receiving/handling loop
    controller = FRBController(intent=intent, project=project, dispatch=dispatch, verbose=verbose)
    obsdoc_client = mcaf_library.ObsdocClient(controller)
    try:
        asyncore.loop()
    except KeyboardInterrupt:
        # Just exit without the trace barf
        logger.info('Escaping mcaf_monitor')


#@click.command()
#@click.option('--intent', '-i', default='', help='Intent to trigger on')
#@click.option('--project', '-p', default='', help='Project name to trigger on')
#@click.option('--dispatch/--do', '-l', help='Only dispatch to multicast or actually do work?', default=True)
#@click.option('--verbose', '-v', help='More verbose output', is_flag=True)
if __name__ == '__main__':
    # This starts the receiving/handling loop

    cmdline = OptionParser()
    cmdline.add_option('-i', '--intent', dest="intent",
        action="store", default="",
        help="[] Trigger on what intent substring?")
    cmdline.add_option('-p', '--project', dest="project",
        action="store", default="",
        help="[] Trigger on what project substring?")
    cmdline.add_option('-d', '--dispatch', dest="dispatch",
        action="store_true", default=False,
        help="[False] Actually run dispatcher; don't just listen to multicast.") 
    cmdline.add_option('-v', '--verbose', dest="verbose",
        action="store_true", default=False,
        help="[False] Verbose output")
    (opt,args) = cmdline.parse_args()
    
    monitor(opt.intent, opt.project, opt.dispatch, opt.verbose)
