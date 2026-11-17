import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.services.compute_discovery import discover, parse_networkctl_neighbors

NETWORKCTL_ETH1 = '''● 3: eth1
                     Link File: /usr/lib/systemd/network/99-default.link
                          Type: ether
                    HW Address: fa:16:3e:86:ca:f2
                       Address: 10.0.29.63 (DHCP4 via 10.0.29.2)
               DHCP4 Client ID: IAID:0x405663a2/DUID
                  Connected To: nth3f-vtn02-public-com-10211071201 on port fe:16:3e:86:ca:f2 (tapf22621a2-d2)'''

NO_LLDP = '__NIC__:eth1\ntcpdump: listening on eth1, link-type EN10MB (Ethernet), snapshot length 262144 bytes\n0 packets captured'

def node(): return SimpleNamespace(id=1, hostname='vm1', address='10.0.29.63')
def session(): return SimpleNamespace(id='s', tsh_version='16.4')
def run_with(stdout, returncode=0, stderr=''):
    with patch('app.services.compute_discovery.run', return_value=SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)):
        return discover(session(), node())

class NetworkctlParseTests(unittest.TestCase):
    def test_parses_connected_to(self):
        self.assertEqual(parse_networkctl_neighbors(NETWORKCTL_ETH1.splitlines()),
                         [('nth3f-vtn02-public-com-10211071201', 'fe:16:3e:86:ca:f2', 'tapf22621a2-d2')])
    def test_multiple_neighbors_on_continuation_lines(self):
        lines = ['  Connected To: sw1 on port Eth1/1 (uplink)', '                sw2 on port Eth1/2', '  Offered DHCP4 Address: x']
        self.assertEqual([n[0] for n in parse_networkctl_neighbors(lines)], ['sw1', 'sw2'])
    def test_no_connected_to(self):
        self.assertEqual(parse_networkctl_neighbors(['  Type: ether', '  Connected To: n/a']), [])

class DiscoverFallbackTests(unittest.TestCase):
    def test_tcpdump_match_has_priority(self):
        out = '__NIC__:eth0\n... System Name TLV (5), length 10: lldp-comp-01\n__NETWORKCTL__:eth0\n' + NETWORKCTL_ETH1
        row = run_with(out)
        self.assertEqual((row['status'], row['nic'], row['compute']), ('DETECTED', 'eth0', 'lldp-comp-01'))
        self.assertNotIn('detail', row)
    def test_networkctl_fallback_when_tcpdump_finds_nothing(self):
        row = run_with(NO_LLDP + '\n__NETWORKCTL__:eth1\n' + NETWORKCTL_ETH1)
        self.assertEqual((row['status'], row['nic'], row['compute']), ('DETECTED', 'eth1', 'nth3f-vtn02-public-com-10211071201'))
        self.assertIn('networkctl', row['detail'])
    def test_networkctl_lines_not_scanned_by_tcpdump_regex(self):
        row = run_with(NO_LLDP + '\n__NETWORKCTL__:eth1\n  Link File: /x/comp-file.link\n  Connected To: n/a')
        self.assertEqual(row['status'], 'NOT_DETECTED')
        self.assertNotIn('NETWORKCTL', row['detail'])
    def test_no_result_from_either_check_keeps_classification(self):
        row = run_with(NO_LLDP + '\n__NETWORKCTL__:eth1\n  Type: ether')
        self.assertEqual((row['status'], row['reason_code']), ('NOT_DETECTED', 'NO_COMPUTE_NEIGHBOR'))
    def test_ssh_failure_unchanged(self):
        row = run_with('', returncode=1, stderr='dial tcp: connection refused')
        self.assertEqual((row['status'], row['reason_code']), ('UNREACHABLE', 'SSH_FAILED'))

if __name__ == '__main__': unittest.main()
