Installation of firewall driver
===============================

.. highlight:: bash

Setting up required software
----------------------------

Create a new user::

  $ sudo adduser fw

Update the package lists, and install the required system software::

  $ sudo apt-get update
  $ sudo apt-get install virtualenvwrapper isc-dhcp-server openvswitch-switch\
    iptables ipset openvswitch-controller git linux-image-generic-lts-raring ntp

Configure ISC-DHCP server::

  $ sudo tee /etc/dhcp/dhcpd.conf <<END
  ddns-update-style none;
  default-lease-time 60000;
  max-lease-time 720000;
  log-facility local7;
  include "/tools/dhcp3/dhcpd.conf.generated";
  END

  $ sudo touch /etc/dhcp/dhcpd.conf.generated
  $ sudo chown fw:fw /etc/dhcp/dhcpd.conf.generated


Configure sudo::

  $ sudo tee /etc/sudoers.d/firewall <<END
  fw ALL= (ALL) NOPASSWD: /sbin/ip netns exec fw ip addr *, /sbin/ip netns exec fw ip ro *, /sbin/ip netns exec fw ip link *, /sbin/ip netns exec fw ipset *, /usr/bin/ovs-vsctl, /sbin/ip netns exec fw iptables-restore -c, /sbin/ip netns exec fw ip6tables-restore -c, /etc/init.d/isc-dhcp-server restart, /sbin/ip link *

  END

  $ sudo chmod 440 /etc/sudoers.d/firewall


Configure sysctl::

  $ sudo tee /etc/sysctl.d/60-circle-firewall.conf <<END
  net.ipv4.ip_forward=1
  net.ipv6.conf.all.forwarding=1
  END

Setting up firewall
-------------------

Clone the git repository::

  $ sudo -i -u fw
  $ git clone git@git.ik.bme.hu:circle/fwdriver.git

Set up *virtualenvwrapper* and the *virtual Python environment* for the project::

  $ source /etc/bash_completion.d/virtualenvwrapper
  $ mkvirtualenv fw

Install the required Python libraries to the virtual environment::

  $ pip install -r fwdriver/requirements.txt

Set up default Firewall configuration::

  $ cat >> ~fw/.virtualenvs/fw/local/bin/postactivate <<END
  export GATEWAY="152.66.243.254"
  export CACHE_URI='pylibmc://${PORTAL_IP}:11211/'
  export AMQP_URI="amqp://guest:guest@localhost:5672/vhost"
  END
  $ exit
  $ sudo cp ~fw/fwdriver/miscellaneous/firewall*.conf /etc/init/



Reboot
------

Reboot::

  $ reboot
