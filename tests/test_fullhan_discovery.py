"""Bounded WS-Discovery packet handling; no physical camera or network access."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'SOURCE/src/contrib/fullhan-discovery/discovery.c'
UUID = '12345678-1234-4234-8234-123456789abc'
ID = '87654321-4321-4321-8321-cba987654321'
DISCOVERY = 'http://schemas.xmlsoap.org/ws/2005/04/discovery'
ADDRESSING = 'http://schemas.xmlsoap.org/ws/2004/08/addressing'
NETWORK = 'http://www.onvif.org/ver10/network/wsdl'
DEVICE = 'http://www.onvif.org/ver10/device/wsdl'
QEMU = shutil.which(os.environ.get('BACKUP_QEMU', os.environ.get('QEMU_ARM', 'qemu-arm')))
ARM_CC = shutil.which(os.environ.get('ARM_CC', str(ROOT / 'SOURCE/toolchain/uclibc/bin/arm-linux-gcc')))


@unittest.skipUnless(shutil.which('cc'), 'Host C compiler required')
class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='fullhan-discovery-')
        cls.directory = Path(cls.temporary.name)
        harness = cls.directory / 'harness.c'
        harness.write_text('#define main discovery_main\n#include "' + str(SOURCE) + '"\n'
                           'int respond(const char *in, char *out, size_t size) {'
                           'return response(in,"' + UUID + '","http://192.0.2.1:5000/",7,out,size);}\n')
        library = cls.directory / 'discovery.so'
        subprocess.run(['cc', '-std=c99', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared', str(harness), '-o', str(library)], check=True, capture_output=True)
        cls.library = ctypes.CDLL(str(library))
        cls.library.respond.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]
        cls.library.respond.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def packet(self, body='<d:Probe/>', action='Probe', message_id='urn:uuid:' + ID):
        return ('<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" xmlns:a="' + ADDRESSING + '" xmlns:d="' + DISCOVERY + '" xmlns:dn="' + NETWORK + '" xmlns:tds="' + DEVICE + '"><s:Header><a:Action>' + DISCOVERY + '/' + action + '</a:Action><a:MessageID>' + message_id + '</a:MessageID></s:Header><s:Body>' + body + '</s:Body></s:Envelope>')

    def respond(self, packet, capacity=4096):
        output = ctypes.create_string_buffer(capacity)
        length = self.library.respond(packet.encode(), output, capacity)
        return length, output.value

    def test_probe_returns_own_address_and_correlated_well_formed_xml(self):
        length, xml = self.respond(self.packet())
        self.assertGreater(length, 0)
        tree = ET.fromstring(xml)
        self.assertEqual(tree.find('.//{' + ADDRESSING + '}RelatesTo').text, 'urn:uuid:' + ID)
        self.assertEqual(tree.find('.//{' + DISCOVERY + '}XAddrs').text, 'http://192.0.2.1:5000/')
        self.assertEqual(tree.find('.//{' + ADDRESSING + '}EndpointReference/{' + ADDRESSING + '}Address').text, 'urn:uuid:' + UUID)

    def test_namespaced_types_and_scope_filter(self):
        self.assertGreater(self.respond(self.packet('<d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types><d:Scopes>onvif://www.onvif.org/name/LSCamoflash</d:Scopes></d:Probe>'))[0], 0)
        for body in ('<d:Probe><d:Types>x:Printer</d:Types></d:Probe>', '<d:Probe><d:Scopes>onvif://www.onvif.org/name/OtherCamera</d:Scopes></d:Probe>'):
            self.assertEqual(self.respond(self.packet(body))[0], 0)

    def test_resolve_requires_own_uuid(self):
        body = '<d:Resolve><a:EndpointReference><a:Address>urn:uuid:' + UUID + '</a:Address></a:EndpointReference></d:Resolve>'
        length, xml = self.respond(self.packet(body, 'Resolve'))
        self.assertGreater(length, 0)
        self.assertIsNotNone(ET.fromstring(xml).find('.//{' + DISCOVERY + '}ResolveMatch'))
        self.assertEqual(self.respond(self.packet(body.replace(UUID, ID), 'Resolve'))[0], 0)

    def test_entities_injection_unknown_actions_and_missing_fields_are_ignored(self):
        for packet in (self.packet(message_id='urn:uuid:' + ID + '&quot;'), '<!DOCTYPE s [<!ENTITY x SYSTEM "file:///etc/passwd">]>' + self.packet(), self.packet(action='Bye'), self.packet().replace('<a:MessageID>', '<a:Wrong>'), self.packet().replace(DISCOVERY, 'http://unrelated.example/')):
            self.assertEqual(self.respond(packet)[0], 0)

    def test_oversized_elements_and_small_output_buffers_are_bounded(self):
        self.assertEqual(self.respond(self.packet('<d:Probe><d:Scopes>' + 'x' * 3000 + '</d:Scopes></d:Probe>'))[0], 0)
        self.assertEqual(self.respond(self.packet(), 32)[0], 0)

    def test_xml_prefix_is_not_fixed(self):
        packet = self.packet('<d:Probe><d:Types xmlns:other="' + DEVICE + '">other:Device</d:Types></d:Probe>').replace('<d:', '<disco:').replace('</d:', '</disco:').replace('xmlns:d=', 'xmlns:disco=').replace('<a:', '<addr:').replace('</a:', '</addr:').replace('xmlns:a=', 'xmlns:addr=')
        self.assertGreater(self.respond(packet)[0], 0)

    def test_type_qname_requires_correct_namespace_not_only_local_name(self):
        for content in ('<d:Types xmlns:evil="urn:printer">evil:Device</d:Types>',
                        '<d:Types>undeclared:NetworkVideoTransmitter</d:Types>',
                        '<d:Types xmlns:dn="urn:printer">dn:NetworkVideoTransmitter</d:Types>',
                        '<d:Types>Device</d:Types>',
                        '<d:Types>tds:NetworkVideoTransmitter</d:Types>',
                        '<d:Types>dn:Device</d:Types>'):
            with self.subTest(content=content):
                self.assertEqual(self.respond(self.packet('<d:Probe>'+content+'</d:Probe>'))[0], 0)
        for content in ('<d:Types>dn:NetworkVideoTransmitter tds:Device</d:Types>',
                        '<d:Types xmlns="'+NETWORK+'">NetworkVideoTransmitter</d:Types>',
                        '<d:Types xmlns:n="'+NETWORK+'">n:NetworkVideoTransmitter</d:Types>'):
            self.assertGreater(self.respond(self.packet('<d:Probe>'+content+'</d:Probe>'))[0], 0)

    def test_element_namespaces_and_soap_structure_are_verified(self):
        packet = self.packet()
        for malformed in (packet.replace('http://www.w3.org/2003/05/soap-envelope', 'urn:wrong-soap'),
                          packet.replace('xmlns:a="'+ADDRESSING+'"', 'xmlns:a="urn:wrong-addressing"'),
                          packet.replace('<d:Probe/>', '<d:Probe xmlns:d="urn:wrong-discovery"/>'),
                          packet.replace('<s:Body><d:Probe/></s:Body>', '<s:Body><d:Wrapper><d:Probe/></d:Wrapper></s:Body>'),
                          packet.replace('<s:Header>', '<s:Header><a:Action>'+DISCOVERY+'/Probe</a:Action>'),
                          packet.replace('<s:Header>', '<s:Header><a:MessageID>urn:uuid:'+ID+'</a:MessageID>'),
                          packet.replace('<d:Probe/>', '<d:Probe/><d:Probe/>'),
                          packet.replace('<s:Header>', '<s:Header><s:Body><d:Probe/></s:Body>')
                                .replace('<s:Body><d:Probe/></s:Body></s:Envelope>', '</s:Envelope>')):
            with self.subTest(packet=malformed):
                self.assertEqual(self.respond(malformed)[0], 0)

    def test_scope_matchby_rejects_unsupported_rules_even_for_empty_scopes(self):
        for rule in (DISCOVERY+'/rfc2396', DISCOVERY+'/rfc3986'):
            body = '<d:Probe><d:Scopes MatchBy="'+rule+'">onvif://www.onvif.org/name</d:Scopes></d:Probe>'
            self.assertGreater(self.respond(self.packet(body))[0], 0)
        for rule in (DISCOVERY+'/strcmp0', 'urn:unknown', ''):
            for content in ('', 'onvif://www.onvif.org/name'):
                body = '<d:Probe><d:Scopes MatchBy="'+rule+'">'+content+'</d:Scopes></d:Probe>'
                self.assertEqual(self.respond(self.packet(body))[0], 0)
        self.assertEqual(self.respond(self.packet('<d:Probe><d:Scopes>onvif://www.onvif.org/name/LSCamoflashWrong</d:Scopes></d:Probe>'))[0], 0)

    def test_namespace_scope_cannot_leak_from_child_to_sibling(self):
        body = ('<d:Probe><d:Types xmlns:local="'+NETWORK+'">local:NetworkVideoTransmitter</d:Types>'
                '<local:Scopes>onvif://www.onvif.org/name/LSCamoflash</local:Scopes></d:Probe>')
        self.assertEqual(self.respond(self.packet(body))[0], 0)
        body = ('<d:Probe><d:Types xmlns:d="'+DISCOVERY+'">dn:NetworkVideoTransmitter</d:Types>'
                '<d:Scopes>onvif://www.onvif.org/name/LSCamoflash</d:Scopes></d:Probe>')
        self.assertGreater(self.respond(self.packet(body))[0], 0)

    def test_default_namespaces_are_scoped_and_attributes_do_not_inherit_them(self):
        body = '<Probe xmlns="'+DISCOVERY+'"><Types>tds:Device</Types><Scopes MatchBy="urn:unsupported"/></Probe>'
        self.assertEqual(self.respond(self.packet(body))[0], 0)
        body = body.replace(' MatchBy="urn:unsupported"', '')
        self.assertGreater(self.respond(self.packet(body))[0], 0)

    def test_resolve_endpoint_and_address_require_addressing_namespace(self):
        body = '<d:Resolve><a:EndpointReference><a:Address>urn:uuid:'+UUID+'</a:Address></a:EndpointReference></d:Resolve>'
        for malformed in (body.replace('<a:EndpointReference>', '<a:EndpointReference xmlns:a="urn:wrong">'),
                          body.replace('<a:Address>', '<a:Address xmlns:a="urn:wrong">'),
                          body.replace('<a:Address>', '<a:Address>urn:uuid:'+UUID+'</a:Address><a:Address>')):
            self.assertEqual(self.respond(self.packet(malformed, 'Resolve'))[0], 0)

    def test_malformed_xml_duplicate_attributes_and_bounded_depth_are_rejected(self):
        packet = self.packet()
        for malformed in (packet.replace('</s:Envelope>', '</other:Envelope>'), packet+packet,
                          packet.replace('<d:Probe/>', '<d:Probe ignored="a" ignored="b"/>'),
                          packet.replace('<d:Probe/>', '<d:Probe xmlns:x="urn:one" xmlns:x="urn:two"/>'),
                          packet.replace('<d:Probe/>', '<d:Probe xmlns:xml="urn:wrong"/>'),
                          packet.replace('<d:Probe/>', '<d:Probe xmlns:x=""/>'),
                          packet.replace('<d:Probe/>', '<d:Probe x:attr="ignored"/>'),
                          packet.replace('<d:Probe/>', '<d:Probe>unexpected text</d:Probe>'),
                          packet.replace('<d:Probe/>', '<d:Probe><d:Types>tds:Device</d:Types><d:Types/></d:Probe>'),
                          packet.replace('<s:Header>', '<s:Header>'+'<a:Extra>'*25+'</a:Extra>'*25)):
            with self.subTest(packet=malformed):
                self.assertEqual(self.respond(malformed)[0], 0)
        self.assertGreater(self.respond('<?xml version="1.0"?>\n'+packet)[0], 0)


@unittest.skipUnless(QEMU and ARM_CC, 'ARM compiler and qemu-arm required')
class ArmDiscoveryTests(DiscoveryTests):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='fullhan-discovery-arm-')
        cls.directory = Path(cls.temporary.name)
        harness = cls.directory / 'harness.c'
        harness.write_text('#define main discovery_main\n#include "'+str(SOURCE)+'"\n#undef main\n'
                           'int main(int argc,char **argv) {char input[8193],output[4096];size_t n;int length;'
                           'size_t size=argc==2?(size_t)atoi(argv[1]):sizeof(output);'
                           'if(size>sizeof(output))return 2;n=fread(input,1,8192,stdin);input[n]=0;'
                           'length=response(input,"'+UUID+'","http://192.0.2.1:5000/",7,output,size);'
                           'if(length>0)fwrite(output,1,(size_t)length,stdout);return length>0?0:1;}\n')
        cls.binary = cls.directory / 'discovery-arm'
        subprocess.run([ARM_CC, '-std=c99', '-Os', '-Wall', '-Wextra', '-Werror', '-static',
                        '-march=armv5te', '-mfloat-abi=soft', '-marm', str(harness), '-o', str(cls.binary)],
                       check=True, capture_output=True, timeout=30)

    def respond(self, packet, capacity=4096):
        result = subprocess.run([QEMU, '-cpu', 'arm1176', str(self.binary), str(capacity)],
                                input=packet.encode(), capture_output=True, timeout=5)
        return len(result.stdout), result.stdout
