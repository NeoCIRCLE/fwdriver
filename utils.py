from os import getenv, devnull
import subprocess as sp
import logging
import json
import re

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

NETNS = getenv('NETNS', 'fw')
MAC = getenv('MAC')
ADDRESSES = json.loads(getenv('ADDRESSES', '{}'))
HA = bool(getenv('HA', False))

# 2013-06-26 12:16:59 DHCPACK on 10.4.0.14 to 5c:b5:24:e6:5c:81
#      (android_b555bfdba7c837d) via vlan0004

dhcp_ack_re = re.compile(r'\S DHCPACK on (?P<ip>[0-9.]+) to '
                         r'(?P<mac>[a-zA-Z0-9:]+) '
                         r'(\((?P<hostname>[^)]+)\) )?'
                         r'via (?P<interface>[a-zA-Z0-9]+)')

# 2013-06-25 11:08:38 DHCPDISCOVER from 48:5b:39:8e:82:78
#      via vlan0005: network 10.5.0.0/16: no free leases

dhcp_no_free_re = re.compile(r'\S DHCPDISCOVER '
                             r'from (?P<mac>[a-zA-Z0-9:]+) '
                             r'via (?P<interface>[a-zA-Z0-9]+):')


def sudo(args, stdin=None):
    FNULL = open(devnull, 'w')
    args = ('/usr/bin/sudo', ) + args
    logger.debug('EXEC {}'.format(' '.join(args)))
    if isinstance(stdin, basestring):
        proc = sp.Popen(args, stdin=sp.PIPE, stderr=FNULL)
        return proc.communicate(stdin)
    else:
        return sp.check_output(args, stderr=FNULL)


def ns_exec(netns, args, stdin=None):
    return sudo(('/sbin/ip', 'netns', 'exec',
                NETNS) + args, stdin)
