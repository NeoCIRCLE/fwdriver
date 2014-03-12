from celery import Celery, task
from os import getenv
import re
import json
from ovs import Switch

DHCP_LOGFILE = getenv('DHCP_LOGFILE', '/var/log/syslog')
VLAN_CONF = getenv('VLAN_CONF', 'vlan.conf')
FIREWALL_CONF = getenv('FIREWALL_CONF', 'firewall.conf')
from utils import NETNS, ns_exec, sudo, ADDRESSES, UPLINK

celery = Celery('tasks', backend='amqp', )
celery.conf.update(CELERY_TASK_RESULT_EXPIRES=300,
                   BROKER_URL=getenv("AMQP_URI"),
                   CELERY_CREATE_MISSING_QUEUES=True)


r'''
 ________
/        \
|install:|
\________/

run as root:

adduser fw
apt-get update
apt-get install virtualenvwrapper isc-dhcp-server openvswitch-switch\
    iptables openvswitch-controller git linux-image-generic-lts-raring

cat > /etc/dhcp/dhcpd.conf <<END
ddns-update-style none;
default-lease-time 60000;
max-lease-time 720000;
log-facility local7;
include "/tools/dhcp3/dhcpd.conf.generated";
END

mkdir -p /tools/dhcp3/
touch /tools/dhcp3/dhcpd.conf.generated && \
    chown fw:fw /tools/dhcp3/dhcpd.conf.generated

cat > /etc/sudoers.d/firewall <<END
fw ALL= (ALL) NOPASSWD: /sbin/ip netns exec fw /sbin/ip addr *, /sbin/ip netns exec fw /sbin/ip ro *, /sbin/ip netns exec fw /sbin/ip link *, /sbin/ip netns exec fw /usr/sbin/ipset *, /usr/bin/ovs-vsctl, /sbin/ip netns exec fw /sbin/iptables-restore -c, /sbin/ip netns exec fw /sbin/ip6tables-restore -c, /etc/init.d/isc-dhcp-server restart, /sbin/ip link *
END

chmod 440 /etc/sudoers.d/firewall

cat > /etc/rc.local <<END
#!/bin/sh -e
/sbin/ip netns add fw
ovs-vsctl del-br firewall
/sbin/ip netns exec fw /etc/init.d/openvswitch-switch restart
/sbin/ip netns exec fw sysctl -f
exit 0
END

cat >> /etc/sysctl.conf <<END
net.ipv4.ip_forward=1
net.ipv6.conf.all.forwarding=1
END

/etc/rc.local

su - fw
git clone git@git.ik.bme.hu:circle/fwdriver.git
mkvirtualenv fw
pip install -r fwdriver/requirements.txt
exit

cp ~fw/fwdriver/miscellaneous/firewall.conf /etc/init/

cat >> ~fw/.virtualenvs/fw/local/bin/postactivate <<END
export UPLINK='["eth1"]'
export GATEWAY="152.66.243.254"
export ADDRESSES='{"vlan0006": ["152.66.243.60/32", "152.66.243.62/32", "152.66.243.97/32", "152.66.243.98/32", "152.66.243.130/32", "152.66.243.147/32", "152.66.243.148/32", "152.66.243.149/32"]}'
export AMQP_URI="amqp://guest:guest@localhost:5672/vhost"
export MAC='02\:00\:98\:42\:f3\:92'
END

reboot

ip netns exec fw ip a

'''


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
    for k, v in ADDRESSES.items():
        data[k]['addresses'] = data[k]['addresses'] + v
    try:
        data[UPLINK[0]] = {'interfaces': UPLINK}
    except:
        pass
    br = Switch('firewall')
    br.migrate(data)
    if onstart is False:
        with open(VLAN_CONF, 'w') as f:
            json.dump(data, f)
    GATEWAY = getenv('GATEWAY', '152.66.243.254')
    try:
        ns_exec(NETNS, ('/sbin/ip', 'ro', 'add', 'default', 'via', GATEWAY))
        ns_exec(NETNS, ('/sbin/ip', 'ro', 'add', '10.12.0.0/22',
                        'via', '10.12.255.253'))
    except:
        pass


@task(name="firewall.reload_dhcp")
def reload_dhcp(data):
    print "dhcp"
    with open('/tools/dhcp3/dhcpd.conf.generated', 'w') as f:
        f.write("\n".join(data) + "\n")
    sudo(('/etc/init.d/isc-dhcp-server', 'restart'))


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
#        raise


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