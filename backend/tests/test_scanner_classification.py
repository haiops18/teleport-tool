import base64, unittest
from types import SimpleNamespace
from unittest.mock import patch
from app.services.scanner import scan_node

class ScannerClassificationTests(unittest.TestCase):
    def record(self,pid,ppid,user,runtime,exe,command,classification):
        encoded=base64.b64encode(command.encode()).decode()
        return f'PROC\t{pid}\t{ppid}\t{user}\t{runtime}\t{exe}\t{encoded}\t/system.slice/teleport.service\t{classification}\tcontrol-group'

    def test_current_scanner_shell_is_not_risk(self):
        output='\n'.join([
            self.record(10,1,'root','00:01','/usr/bin/dash','sh -c scanner','SCAN_INTERNAL'),
            self.record(11,10,'root','00:00','/usr/bin/ps','ps','SCAN_INTERNAL'),
            self.record(12,1,'app','01:00','/usr/bin/java','java -jar app.jar','RISK')])
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'WARNING'); self.assertEqual(len(rows),1); self.assertEqual(rows[0]['pid'],12)
    def test_only_scanner_tree_is_safe(self):
        output=self.record(10,1,'root','00:01','/usr/bin/dash','sh -c scanner','SCAN_INTERNAL')
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'SAFE'); self.assertEqual(rows,[{'status':'SAFE','kill_mode':'control-group'}])
    def test_real_bash_outside_current_tree_is_risk(self):
        output=self.record(20,1,'app','01:00','/bin/bash','/bin/bash /opt/app/run.sh','RISK')
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'WARNING'); self.assertEqual(rows[0]['pid'],20)

    def test_multiline_command_is_one_risk_record(self):
        command='bash -c "\n  while true; do\n    sleep 5\n  done\n"'
        output=self.record(30,1,'root','01:00','/usr/bin/bash',command,'RISK')
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'WARNING')
        self.assertEqual(rows[0]['command_line'],command)

    def test_invalid_protocol_is_not_safe(self):
        output='PROC\t30\t1\troot\t01:00\t/usr/bin/bash\t!!!\t/system.slice/teleport.service\tRISK\tcontrol-group'
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'ERROR')
        self.assertEqual(rows[0]['error_message'],'SCAN_PROTOCOL_INVALID')

    def test_token_is_redacted_before_a_risk_result_is_persisted(self):
        output=self.record(31,1,'root','01:00','/usr/bin/bash','bash --token=TOPSECRET worker','RISK')
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            _,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertNotIn('TOPSECRET',rows[0]['command_line'])
        self.assertIn('--token=********',rows[0]['command_line'])

    def test_active_teleport_session_tree_is_not_risk(self):
        output='\n'.join([
            self.record(778,1,'root','01:00','/usr/local/bin/teleport','teleport start','TELEPORT_CORE'),
            self.record(2306095,778,'root','00:01','/usr/local/bin/teleport','teleport exec','TELEPORT_SESSION'),
            self.record(2306145,2306095,'root','00:01','/usr/bin/bash','-bash','TELEPORT_SESSION'),
            self.record(2306189,2306145,'root','00:01','/usr/bin/systemctl','systemctl status teleport','TELEPORT_SESSION'),
            self.record(2306190,2306189,'root','00:01','/usr/bin/less','pager','TELEPORT_SESSION'),
            self.record(2292468,1,'root','01:00','/usr/bin/bash','bash -c teleport-killmode-test','RISK')])
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'WARNING')
        self.assertEqual([row['pid'] for row in rows],[2292468])

    def test_detached_risk_descendants_do_not_inflate_risk_count(self):
        output='\n'.join([
            self.record(2292468,1,'root','01:00','/usr/bin/bash','bash -c teleport-killmode-test','RISK'),
            self.record(2306161,2292468,'root','00:00','/usr/bin/sleep','sleep 5','RISK')])
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'WARNING')
        self.assertEqual([row['pid'] for row in rows],[2292468])

    def test_killmode_process_marks_external_as_protected(self):
        output=self.record(99,1,'app','01:00','/usr/bin/java','java -jar app.jar','EXTERNAL_PROTECTED').replace('\tcontrol-group','\tprocess')
        with patch('app.services.scanner.run',return_value=SimpleNamespace(returncode=0,stdout=output,stderr='')):
            status,rows=scan_node(SimpleNamespace(id='s',tsh_version='16.4'),SimpleNamespace(hostname='n'))
        self.assertEqual(status,'SAFE')
        self.assertEqual(rows[0]['classification'],'EXTERNAL_PROTECTED')
