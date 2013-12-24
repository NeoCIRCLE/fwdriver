from celery import Celery, task
from os import getenv
import re
import json
from ovs import Switch

IRC_CHANNEL = getenv('IRC_CHANNEL', '/home/cloud/irc/irc.atw.hu/#ik/in')
DHCP_LOGFILE = getenv('DHCP_LOGFILE', '/var/log/syslog')
VLAN_CONF = getenv('VLAN_CONF', 'vlan.conf')
FIREWALL_CONF = getenv('FIREWALL_CONF', 'firewall.conf')
from utils import NETNS, ns_exec

celery = Celery('tasks', backend='amqp', )
celery.conf.update(CELERY_TASK_RESULT_EXPIRES=300,
                   BROKER_URL=getenv("AMQP_URI"),
                   CELERY_CREATE_MISSING_QUEUES=True)


@task(name="firewall.reload_firewall")
def reload_firewall(data4, data6, onstart=False):
    print "fw"

    ns_exec(NETNS, ('/sbin/ip6tables-restore', '-c'),
            '\n'.join(data6['filter']) + '\n')

    ns_exec(NETNS, ('/sbin/iptables-restore', '-c'),
            ('\n'.join(data4['filter']) + '\n' +
             '\n'.join(data4['nat']) + '\n'))

    if onstart is False:
        with open(FIREWALL_CONF, 'w') as f:
            json.dump([data4, data6], f)


@task(name="firewall.reload_firewall_vlan")
def reload_firewall_vlan(data, onstart=False):
    print "fw vlan"
    br = Switch('firewall')
    br.migrate(data)
    if onstart is False:
        with open(VLAN_CONF, 'w') as f:
            json.dump(data, f)
    GATEWAY = getenv('GATEWAY', '152.66.243.254')
    try:
       ns_exec(NETNS, ('/sbin/ip', 'ro', 'add', 'default', 'via', GATEWAY))
    except:
       pass


@task(name="firewall.reload_dhcp")
def reload_dhcp(data):
    print "dhcp"
    with open('/tools/dhcp3/dhcpd.conf.generated', 'w') as f:
        f.write("\n".join(data) + "\n")
    ns_exec(NETNS, ('/etc/init.d/isc-dhcp-server', 'restart'))


def ipset_save(data):
    r = re.compile(r'^add blacklist ([0-9.]+)$')

    data_new = [x['ipv4'] for x in data]
    data_old = []

    lines = ns_exec(NETNS, ('/usr/sbin/ipset', 'save', 'blacklist'))
    for line in lines.splitlines():
        x = r.match(line.rstrip())
        if x:
            data_old.append(x.group(1))

    l_add = list(set(data_new).difference(set(data_old)))
    l_del = list(set(data_old).difference(set(data_new)))

    return (l_add, l_del)


def ipset_restore(l_add, l_del):
    ipset = []
    ipset.append('create blacklist hash:ip family inet hashsize '
                 '4096 maxelem 65536')
    ipset = ipset + ['add blacklist %s' % x for x in l_add]
    ipset = ipset + ['del blacklist %s' % x for x in l_del]

    ns_exec(NETNS, ('/usr/sbin/ipset', 'restore', '-exist'),
            '\n'.join(ipset) + '\n')


@task(name="firewall.reload_blacklist")
def reload_blacklist(data):
    print "blacklist"

    l_add, l_del = ipset_save(data)
    ipset_restore(l_add, l_del)


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


@task(name="firewall.get_dhcp_clients")
def get_dhcp_clients():
    clients = {}

    with open(DHCP_LOGFILE, 'r') as f:
        for line in f:
            m = dhcp_ack_re.search(line)
            if m is None:
                m = dhcp_no_free_re.search(line)
                if m is None:
                    continue

            m = m.groupdict()
            mac = m['mac']
            ip = m.get('ip', None)
            hostname = m.get('hostname', None)
            interface = m.get('interface', None)
            clients[mac] = {'ip': ip, 'hostname': hostname,
                            'interface': interface}

    return clients


def start_firewall():
    try:
        ns_exec(NETNS, ('/usr/sbin/ipset', 'create', 'blacklist',
                        'hash:ip', 'family', 'inet', 'hashsize',
                        '4096', 'maxelem', '65536'))
    except:
        pass
    try:
        with open(FIREWALL_CONF, 'r') as f:
            data4, data6 = json.load(f)
            reload_firewall(data4, data6, True)
    except:
        print 'nemsikerult:('
        raise


def start_networking():
    try:
        with open(VLAN_CONF, 'r') as f:
            data = json.load(f)
            reload_firewall_vlan(data, True)
    except:
        print 'nemsikerult:('
        raise


def main():
    start_networking()
    start_firewall()

main()
