from netaddr import IPNetwork
from subprocess import CalledProcessError
import logging

from utils import NETNS, sudo, ns_exec, HA

logger = logging.getLogger(__name__)


class Interface(object):
    def __init__(self, name, data, with_show=False):
        # {"interfaces": ["eth1"], "tag": 2, "trunks": [1, 2, 3],
        # "type": "internal", "addresses": ["193.006.003.130/24", "None"]}
        self.name = name
        self.is_internal = data.get('type', 'external') == 'internal'

        try:
            self.tagged = frozenset(int(i) for i in data['trunks'])
        except (TypeError, KeyError):
            self.tagged = frozenset()

        untagged = data.get('tag')
        if (untagged and not self.tagged and unicode(untagged).isdecimal()):
            self.untagged = int(untagged)
        else:
            self.untagged = None

        if with_show:
            data['addresses'] = self.show()
        try:
            self.addresses = frozenset(IPNetwork(i) for i in data['addresses']
                                       if i != 'None')
        except (TypeError, KeyError):
            self.addresses = frozenset()

    def __repr__(self):
        return '<Interface: %s veth=%s| untagged=%s tagged=%s addrs=%s>' % (
            self.name, self.is_internal, self.untagged, self.tagged,
            self.addresses)

    def __eq__(self, other):
        return self.__dict__ == other.__dict__

    def __hash__(self):
        return reduce(lambda acc, x: acc ^ hash(x),
                      self.__dict__.values(), 0)

    @property
    def external_name(self):
        if self.is_internal:
            return '%s-EXT' % self.name
        else:
            return self.name

    def _run(self, *args):
        args = ('ip', 'addr', ) + args
        return ns_exec(args)

    def show(self):
        retval = []
        try:
            for line in self._run('show', self.name,
                                  'scope', 'global').splitlines():
                t = line.split()
                if len(t) > 0 and t[0] in ('inet', 'inet6'):
                    retval.append(IPNetwork(t[1]))
        except CalledProcessError:
            pass

        logger.debug('[ip-%s] show: %s', self.name, str(retval))
        return retval

    def delete_address(self, address):
        self._run('del', str(address), 'dev', self.name)

    def add_address(self, address):
        self._run('add', str(address), 'dev', self.name)

    def up(self):
        if self.is_internal:
            ns_exec(('ip', 'link', 'set', 'up', self.name))
        sudo(('ip', 'link', 'set', 'up', self.external_name))

    def migrate(self):
        old_addresses = [str(x) for x in self.show()]
        new_addresses = [str(x) for x in self.addresses]
        to_delete = list(set(old_addresses) - set(new_addresses))
        to_add = list(set(new_addresses) - set(old_addresses))

        logger.debug('[ip-%s] delete: %s', self.name, str(to_delete))
        logger.debug('[ip-%s] add: %s', self.name, str(to_add))

        for i in to_delete:
            self.delete_address(i)

        for i in to_add:
            self.add_address(i)


class Switch(object):
    def __init__(self, brname):
        self.brname = brname
        try:
            self._run('add-br', brname)
        except:
            pass

    def _run(self, *args):
        args = ('ovs-vsctl', ) + args
        return sudo(args)

    def _setns(self, dev):
        args = ('ip', 'link', 'set', dev, 'netns', NETNS)
        return sudo(args)

    def list_ports(self):
        ovs = {}
        bridge = None
        port = None
        # parse ovs-vsctl show
        for line in self._run('show').splitlines():
            t = line.split()
            if t[0] == 'Bridge':
                bridge = t[1]
                ovs[bridge] = {}
            elif t[0] == 'Port':
                port = t[1].replace('"', '')  # valahol idezojel van
                if port.endswith('-EXT'):
                    port = port.rstrip('-EXT')
                    type = 'internal'
                else:
                    type = 'external'
                ovs[bridge][port] = {'type': type}
            elif t[0] == 'tag:':
                ovs[bridge][port]['tag'] = int(t[1])
            elif t[0] == 'trunks:':
                trunks = [int(p.strip('[,]')) for p in t[1:]]
                ovs[bridge][port]['trunks'] = trunks
        # Create Interface objects
        return [Interface(name, data, with_show=True)
                for name, data in ovs.get(self.brname, {}).items()
                if name != self.brname]

    def add_port(self, interface):
        params = ['add-port', self.brname, interface.external_name]
        if interface.untagged:
            params.append('tag=%d' % int(interface.untagged))
        if interface.tagged:
            params.append('trunks=%s' % list(interface.tagged))

        # move interface into namespace
        try:
            if interface.is_internal:
                sudo(('ip', 'link', 'add', interface.external_name,
                      'type', 'veth', 'peer', 'name', interface.name))
                self._setns(interface.name)
        except:
            logger.exception('Unhandled exception: ')
        self._run(*params)

    def delete_port(self, interface):
        self._run('del-port', self.brname, interface.external_name)
        if interface.is_internal:
            try:
                sudo(('ip', 'link', 'del', interface.external_name))
            except CalledProcessError:
                pass

    def migrate(self, new_ports):
        old_interfaces = self.list_ports()
        new_interfaces = [Interface(port, data)
                          for port, data in new_ports.items()]

        add = list(set(new_interfaces).difference(set(old_interfaces)))
        delete = list(set(old_interfaces).difference(set(new_interfaces)))

        logger.debug('[ovs delete]: %s', delete)
        logger.debug('[ovs add]: %s', add)

        for interface in delete:
            self.delete_port(interface)

        for interface in add:
            self.add_port(interface)

        for interface in new_interfaces:
            try:
                if interface.is_internal or not HA:
                    interface.up()
            except CalledProcessError as e:
                logger.warning(e)
            try:
                interface.migrate()
            except CalledProcessError as e:
                logger.warning(e)
