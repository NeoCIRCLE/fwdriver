import subprocess
from netaddr import IPNetwork

# data = subprocess.check_output('sudo ovs-vsctl --format=json --data=json '
#                                '--no-headings find Interface', shell=True)

# obj = json.loads(data)

# print json.dumps(obj['data'][0], indent=4)


class IPDevice:
    def __init__(self, devname):
        self.devname = devname

    def _run(self, *args):
        args = ('sudo', 'ip', 'addr', ) + args
#        print args
        return subprocess.check_output(args)

    def show(self):
        retval = []
        for line in self._run('show', self.devname,
                              'scope', 'global').splitlines():
            t = line.split()
            if len(t) > 0 and t[0] in ('inet', 'inet6'):
                retval.append(IPNetwork(t[1]))
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

        print delete, add

        for i in delete:
            self.delete(i)

        for i in add:
            self.add(i)


class Switch:
    def __init__(self, brname):
        self.brname = brname

    def _run(self, *args):
        args = ('sudo', 'ovs-vsctl', ) + args
        return subprocess.check_output(args)

    def list_ports(self):
        retval = {}
        c_bridge = None
        c_port = None
        for line in self._run('show').splitlines():
            t = line.split()
            if t[0] == 'Bridge':
                c_bridge = t[1]
                retval[c_bridge] = {}
            elif t[0] == 'Port':
                c_port = t[1]
                retval[c_bridge][c_port] = {}
            elif t[0] == 'tag:':
                retval[c_bridge][c_port]['tag'] = int(t[1])
            elif t[0] == 'type:':
                retval[c_bridge][c_port]['type'] = t[1]
        return retval.get(self.brname, {})

    def add_port(self, name, tag):
        self._run('add-port', self.brname, name, 'tag=%d' % int(tag), '--',
                  'set', 'Interface', name, 'type=internal')
        subprocess.check_output(['sudo', 'ip', 'link', 'set', 'up', name])

    def delete_port(self, name):
        self._run('del-port', self.brname, name)

    def migrate(self, new_ports):
        old_ports = self.list_ports()
        add = []
        delete = []

        for port, data in new_ports.items():
            if port not in old_ports:
                add.append(port)
            elif (old_ports[port].get('tag', None) !=
                    new_ports[port].get('tag', None)):
                delete.append(port)
                add.append(port)

        delete = delete + list(set(old_ports.keys()) -
                               set(new_ports.keys()))
        delete.remove(self.brname)

        print delete, add

        for i in delete:
            self.delete_port(i)
        for i in add:
            self.add_port(i, new_ports[i]['tag'])

        for port, data in new_ports.items():
            interface = IPDevice(devname=port)
            interface.migrate([IPNetwork(x)
                               for x in data['addresses']
                               if x != 'None'])
