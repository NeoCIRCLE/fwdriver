import subprocess
from netaddr import IPNetwork
import logging


class IPDevice:
    def __init__(self, devname):
        self.devname = devname

    def _run(self, *args):
        args = ('sudo', 'ip', 'addr', ) + args
        logging.debug('subprocess_check_output: {}'.format(args))
        return subprocess.check_output(args)

    def show(self):
        retval = []
        for line in self._run('show', self.devname,
                              'scope', 'global').splitlines():
            t = line.split()
            if len(t) > 0 and t[0] in ('inet', 'inet6'):
                retval.append(IPNetwork(t[1]))
        logging.debug('[ip-%s] show: %s' % (self.devname, str(retval)))
        return retval

    def delete(self, address):
        self._run('del', str(address), 'dev', self.devname)

    def add(self, address):
        self._run('add', str(address), 'dev', self.devname)

    def migrate(self, new_addresses):
        old_addresses = [str(x) for x in self.show()]
        new_addresses = [str(x) for x in new_addresses]
        delete = list(set(old_addresses) - set(new_addresses))
        add = list(set(new_addresses) - set(old_addresses))

        logging.debug('[ip-%s] delete: %s' % (self.devname, str(delete)))
        logging.debug('[ip-%s] add: %s' % (self.devname, str(add)))

        for i in delete:
            self.delete(i)

        for i in add:
            self.add(i)


class Switch:
    def __init__(self, brname):
        self.brname = brname
        try:
            self._run('add-br', brname)
        except:
            pass

    def _run(self, *args):
        args = ('sudo', 'ovs-vsctl', ) + args
        return subprocess.check_output(args)

    def list_ports(self):
        retval = {}
        bridge = None
        port = None
        for line in self._run('show').splitlines():
            t = line.split()
            if t[0] == 'Bridge':
                bridge = t[1]
                retval[bridge] = {}
            elif t[0] == 'Port':
                port = t[1].replace('"', '')  # valahol idezojel van
                retval[bridge][port] = {}
                retval[bridge][port]['interfaces'] = []
            elif t[0] == 'Interface':
                interface = t[1].replace('"', '')  # valahol idezojel van
                retval[bridge][port]['interfaces'].append(interface)
            elif t[0] == 'tag:':
                tag = int(t[1])
                retval[bridge][port]['tag'] = tag
            elif t[0] == 'type:':
                retval[bridge][port]['type'] = t[1]
            elif t[0] == 'trunks:':
                trunks = [int(p.strip('[,]')) for p in t[1:]]
                retval[bridge][port]['trunks'] = trunks
        return retval.get(self.brname, {})

    def add_port(self, name, interfaces, tag, trunks, internal=True):
        if len(interfaces) > 1:
            # bond
            params = ['add-bond', self.brname,
                      name] + interfaces + ['tag=%d' % int(tag)]
        else:
            params = ['add-port', self.brname, name, 'tag=%d' % int(tag)]
        if internal:
            params = params + ['--',  'set', 'Interface', interfaces[0],
                               'type=internal']
        if trunks is not None and len(trunks) > 0:
            params.append('trunks=%s' % trunks)
        self._run(*params)
        self.ip_link_up(interfaces)

    def ip_link_up(self, interfaces):
        for interface in interfaces:
            try:
                subprocess.check_output(['sudo', 'ip', 'link',
                                         'set', 'up', interface])
            except:
                pass

    def delete_port(self, name):
        self._run('del-port', self.brname, name)

    def migrate(self, new_ports):
        old_ports = self.list_ports()
        add = []
        delete = []

        for port, data in new_ports.items():
            if port not in old_ports:
                # new port
                add.append(port)
            elif (old_ports[port].get('tag', None) !=
                    new_ports[port].get('tag', None) or
                    old_ports[port].get('trunks', None) !=
                    new_ports[port].get('trunks', None) or
                    old_ports[port].get('interfaces', None) !=
                    new_ports[port].get('interfaces', None)):
                # modified port
                delete.append(port)
                add.append(port)

        delete = delete + list(set(old_ports.keys()) -
                               set(new_ports.keys()))
        delete.remove(self.brname)

        logging.debug('[ovs delete: %s' % (delete, ))
        logging.debug('[ovs] add: %s' % (add, ))

        for i in delete:
            self.delete_port(i)
        for i in add:
            internal = new_ports[i].get('type', '') == 'internal'
            tag = new_ports[i]['tag']
            trunks = new_ports[i].get('trunks', [])
            interfaces = new_ports[i]['interfaces']
            self.add_port(i, interfaces, tag, trunks, internal)

        for port, data in new_ports.items():
            interface = IPDevice(devname=port)
            try:
                interface.migrate([IPNetwork(x)
                                   for x in data.get('addresses', [])
                                  if x != 'None'])
            except:
                pass
