from celery import Celery, task
from os import getenv
import re
import json
import logging

from utils import (ns_exec, sudo, ADDRESSES, get_network_type,
                   dhcp_no_free_re, dhcp_ack_re)

DHCP_LOGFILE = getenv('DHCP_LOGFILE', '/var/log/syslog')
VLAN_CONF = getenv('VLAN_CONF', 'vlan.conf')
FIREWALL_CONF = getenv('FIREWALL_CONF', 'firewall.conf')

CACHE_URI = getenv('CACHE_URI')
AMQP_URI = getenv('AMQP_URI')

celery = Celery('tasks',)
celery.conf.update(CELERY_TASK_RESULT_EXPIRES=300,
                   BROKER_URL=AMQP_URI,
                   CELERY_CREATE_MISSING_QUEUES=True)

celery.conf.update(CELERY_CACHE_BACKEND=CACHE_URI,
                   CELERY_RESULT_BACKEND='cache')

logger = logging.getLogger(__name__)


@task(name="firewall.reload_firewall")
def reload_firewall(data4, data6, save_config=True):
    try:
        ns_exec(('ip6tables-restore', '-c'), data6)
        ns_exec(('iptables-restore', '-c'), data4)
    except:
        logging.exception('Unhandled exception: ')
        raise

    if save_config:
        with open(FIREWALL_CONF, 'w') as f:
            json.dump([data4, data6], f)

    logger.info("Firewall configuration is reloaded.")


@task(name="firewall.reload_firewall_vlan")
def reload_firewall_vlan(data, save_config=True):
    network_type = get_network_type()
    if network_type is None:
        logger.info("Ignored reload_firewall_vlan() network type=%s",
                    network_type)
        return
    # Add additional addresses from config
    for k, v in ADDRESSES.items():
        data[k]['addresses'] += v

    uplink = getenv('UPLINK', None)
    if uplink:
        data[uplink] = {'interfaces': uplink}

    print network_type
    br = network_type('firewall')
    br.migrate(data)

    if save_config:
        with open(VLAN_CONF, 'w') as f:
            json.dump(data, f)

    try:
        ns_exec(('ip', 'ro', 'add', 'default', 'via',
                 getenv('GATEWAY', '152.66.243.254')))
    except:
        pass

    logger.info("Interface (vlan) configuration is reloaded.")


@task(name="firewall.reload_dhcp")
def reload_dhcp(data):
    with open('/etc/dhcp/dhcpd.conf.generated', 'w') as f:
        f.write("\n".join(data) + "\n")
    import platform
    if platform.dist()[0]=="centos":
        sudo(('/bin/systemctl', 'restart','dhcpd'))
    else:
        sudo(('/etc/init.d/isc-dhcp-server', 'restart'))
    logger.info("DHCP configuration is reloaded.")


def ipset_save(data):
    r = re.compile(r'^add blacklist ([0-9.]+)$')

    data_new = [x['ipv4'] for x in data]
    data_old = []

    lines = ns_exec(('ipset', 'save', 'blacklist'))
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
    ipset += ['add blacklist %s' % x for x in l_add]
    ipset += ['del blacklist %s' % x for x in l_del]

    ns_exec(('ipset', 'restore', '-exist'),
            '\n'.join(ipset) + '\n')


@task(name="firewall.reload_blacklist")
def reload_blacklist(data):
    l_add, l_del = ipset_save(data)
    ipset_restore(l_add, l_del)
    logger.info("Blacklist configuration is reloaded.")


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
        ns_exec(('ipset', 'create', 'blacklist', 'hash:ip',
                 'family', 'inet', 'hashsize', '4096', 'maxelem',
                 '65536'))
    except:
        pass
    try:
        with open(FIREWALL_CONF, 'r') as f:
            data4, data6 = json.load(f)
            reload_firewall(data4, data6, True)
    except Exception:
        logger.exception('Unhandled exception: ')


def start_networking():
    try:
        with open(VLAN_CONF, 'r') as f:
            data = json.load(f)
            reload_firewall_vlan(data, True)
    except Exception:
        logger.exception('Unhandled exception: ')


def main():
    start_networking()
    start_firewall()


main()
