#!/usr/bin/env python
#  Author:
#  Muhammad Shahbaz (muhammad.shahbaz@gatech.edu)
#  Rudiger Birkner (Networked Systems Group ETH Zurich)
#  Arpit Gupta (Princeton)


import argparse
import json
from multiprocessing.connection import Listener, Client
import os
import Queue
from threading import Thread

import sys
np = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if np not in sys.path:
    sys.path.append(np)
import util.log

from core import XRSPeer
from server import server as Server


logger = util.log.getLogger('XRS')

class route_server(object):

    def __init__(self, config_file):
        logger.info("Initializing the Route Server.")

        # Init the Route Server
        self.server = None
        self.ah_socket = None
        self.participants = {}

        # Several useful mappings
        self.port_2_participant = {}
        self.participant_2_port = {}
        self.portip_2_participant = {}
        self.participant_2_portip = {}
        self.portmac_2_participant = {}
        self.participant_2_portmac = {}
        self.asn_2_participant = {}
        self.participant_2_asn = {}

        ## Parse Config
        self.parse_config(config_file)

        # Initialize a XRS Server
        self.server = Server(logger)
        self.run = True

        """
        Start the announcement Listener which will receive announcements
        from participants's controller and put them in XRS's sender queue.
        """
        self.set_announcement_handler()


    def start(self):
        logger.info("Starting the Server to handle incoming BGP Updates.")
        self.server.start()

        waiting = 0

        while self.run:
            # get BGP messages from ExaBGP via stdin
            try:
                route = self.server.receiver_queue.get(True, 1)
                route = json.loads(route)

                waiting = 0

                logger.debug("Got route from ExaBGP. "+str(route)+' '+str(type(route)))

                # Received BGP route advertisement from ExaBGP
                for id, peer in self.participants.iteritems():
                    # Apply the filtering logic
                    advertiser_ip = route['neighbor']['ip']
                    if advertiser_ip in self.portip_2_participant:
                        advertise_id = self.portip_2_participant[advertiser_ip]
                        if id in self.participants[advertise_id].peers_out and advertise_id in self.participants[id].peers_in:
                            # Now send this route to participant `id`'s controller'
                            self.send_update(id, route)

            except Queue.Empty:
                if waiting == 0:
                    logger.debug("Waiting for BGP update...")
                    waiting = 1
                else:
                    waiting = (waiting % 30) + 1
                    if waiting == 30:
                        logger.debug("Waiting for BGP update...")


    def parse_config(self, config_file):
        # loading config file

        logger.debug("Begin parsing config...")

        config = json.load(open(config_file, 'r'))

        self.ah_socket = tuple(config["Route Server"]["AH_SOCKET"])

        for participant_name in config["Participants"]:
            participant = config["Participants"][participant_name]

            # adding asn and mappings
            asn = participant["ASN"]
            self.asn_2_participant[participant["ASN"]] = int(participant_name)
            self.participant_2_asn[int(participant_name)] = participant["ASN"]

            self.participant_2_port[int(participant_name)] = []
            self.participant_2_portip[int(participant_name)] = []
            self.participant_2_portmac[int(participant_name)] = []

            for i in range(0, len(participant["Ports"])):
                self.port_2_participant[participant["Ports"][i]['Id']] = int(participant_name)
                self.portip_2_participant[participant["Ports"][i]['IP']] = int(participant_name)
                self.portmac_2_participant[participant["Ports"][i]['MAC']] = int(participant_name)
                self.participant_2_port[int(participant_name)].append(participant["Ports"][i]['Id'])
                self.participant_2_portip[int(participant_name)].append(participant["Ports"][i]['IP'])
                self.participant_2_portmac[int(participant_name)].append(participant["Ports"][i]['MAC'])

            # adding ports and mappings
            ports = [{"ID": participant["Ports"][i]['Id'],
                         "MAC": participant["Ports"][i]['MAC'],
                         "IP": participant["Ports"][i]['IP']}
                         for i in range(0, len(participant["Ports"]))]

            peers_out = [peer for peer in participant["Peers"]]
            # TODO: Make sure this is not an insane assumption
            peers_in = peers_out

            temp = participant["EH_SOCKET"]
            eh_socket = (str(temp[0]), int(temp[1]))

            # create peer and add it to the route server environment
            self.participants[int(participant_name)] = XRSPeer(asn, ports, peers_in, peers_out, eh_socket)

        logger.debug("Done parsing config")


    def set_announcement_handler(self):
        '''Start the listener socket for BGP Announcements'''

        logger.info("Starting the announcement handler...")

        self.listener_eh = Listener(self.ah_socket, authkey=None)
        ps_thread = Thread(target=self.start_ah)
        ps_thread.daemon = True
        ps_thread.start()


    def start_ah(self):
        '''Announcement Handler '''

        logger.info("Announcement Handler started.")

        while True:
            conn_ah = self.listener_eh.accept()
            tmp = conn_ah.recv()

            logger.debug("Received an announcement.")

            announcement = json.loads(tmp)
            self.server.sender_queue.put(announcement)
            reply = "Announcement processed"
            conn_ah.send(reply)
            conn_ah.close()


    def send_update(self, id, route):
        # TODO: Explore what is better, persistent client sockets or
        # new socket for each BGP update
        "Send this BGP route to participant id's controller"
        logger.debug("Sending a route update to participant "+str(id))
        conn = Client(tuple(self.participants[id].eh_socket), authkey = None)
        data = {}
        data['bgp'] = route
        conn.send(json.dumps(data))
        recv = conn.recv()
        conn.close()


    def stop(self):

        logger.info("Stopping.")
        self.run = False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('dir', help='the directory of the example')
    args = parser.parse_args()

    # locate config file
    base_path = os.path.abspath(os.path.join(os.path.dirname(os.path.realpath(__file__)),"..","examples",args.dir,"config"))
    config_file = os.path.join(base_path, "sdx_global.cfg")

    # start route server
    sdx_rs = route_server(config_file)
    rs_thread = Thread(target=sdx_rs.start)
    rs_thread.daemon = True
    rs_thread.start()

    while rs_thread.is_alive():
        try:
            rs_thread.join(1)
        except KeyboardInterrupt:
            sdx_rs.stop()


if __name__ == '__main__':
    main()
