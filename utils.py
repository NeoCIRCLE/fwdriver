from os import getenv, devnull
import subprocess as sp
import logging
import json

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

NETNS = getenv('NETNS', 'fw')
MAC = getenv('MAC')
UPLINK = json.loads(getenv('UPLINK', '[]'))
ADDRESSES = json.loads(getenv('ADDRESSES', '{}'))


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
