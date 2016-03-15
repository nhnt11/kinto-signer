from base64 import b64decode, urlsafe_b64encode
import tempfile
import re
import os

import mock
import pytest

from kinto_signer.signer import ECDSASigner, AutographSigner, BadSignatureError
from kinto_signer.signer import autograph
from kinto_signer.signer import local_ecdsa
from .support import unittest


SIGNATURE = (
    "ikfq6qOV85vR7QaNCTldVvvtcNpPIICqqMp3tfyiT7fHCgFNq410SFnIfjAPgSa"
    "jEtxxyGtZFMoI/BzO/1y5oShLtX0LH4wx/Wft7wz17T7fFqpDQ9hFZzTOPBwZUIbx")


def save_key(key, key_name):
    tmp = tempfile.mktemp(key_name)
    with open(tmp, 'wb+') as tmp_file:
        tmp_file.write(key)
    return tmp


class ECDSASignerTest(unittest.TestCase):

    @classmethod
    def get_backend(cls, **options):
        return ECDSASigner(**options)

    @classmethod
    def setUpClass(cls):
        sk, vk = ECDSASigner.generate_keypair()
        cls.sk_location = save_key(sk, 'signing-key')
        cls.vk_location = save_key(vk, 'verifying-key')
        cls.signer = cls.get_backend(private_key=cls.sk_location)

    @classmethod
    def tearDownClass(cls):
        os.remove(cls.sk_location)
        os.remove(cls.vk_location)

    def test_keyloading_fails_if_no_settings(self):
        backend = self.get_backend(public_key=self.vk_location)
        with pytest.raises(ValueError):
            backend.load_private_key()

    def test_key_loading_works(self):
        key = self.signer.load_private_key()
        assert key is not None

    def test_signer_roundtrip(self):
        signature = self.signer.sign("this is some text")
        self.signer.verify("this is some text", signature)

    def test_base64url_encoding(self):
        signature_bundle = self.signer.sign("this is some text")
        b64signature = signature_bundle['signature']

        decoded_signature = b64decode(b64signature.encode('utf-8'))
        b64urlsignature = urlsafe_b64encode(decoded_signature).decode('utf-8')
        signature_bundle['signature'] = b64urlsignature
        signature_bundle['signature_encoding'] = 'rs_base64url'

        self.signer.verify("this is some text", signature_bundle)

    def test_wrong_signature_raises_an_error(self):
        signature_bundle = {
            'signature': SIGNATURE,
            'hash_algorithm': 'sha384',
            'signature_encoding': 'rs_base64'}

        with pytest.raises(BadSignatureError):
            self.signer.verify(
                "Text not matching with the sig.",
                signature_bundle)

    def test_unsupported_hash_algorithm_raises(self):
        signature_bundle = {
            'signature': SIGNATURE,
            'hash_algorithm': 'sha256',
            'signature_encoding': 'rs_base64'}

        with pytest.raises(ValueError) as excinfo:
            self.signer.verify(
                "Text not matching with the sig.",
                signature_bundle)
        assert str(excinfo.value) == "Unsupported hash_algorithm: sha256"

    def test_unsupported_signature_encoding_raises(self):
        signature_bundle = {
            'signature': SIGNATURE,
            'hash_algorithm': 'sha384',
            'signature_encoding': 'base64'}

        with pytest.raises(ValueError) as excinfo:
            self.signer.verify(
                "Text not matching with the sig.",
                signature_bundle)
        assert str(excinfo.value) == "Unsupported signature_encoding: base64"

    def test_signer_returns_a_base64_string(self):
        signature = self.signer.sign("this is some text")['signature']
        hexa_regexp = (
            r'^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}'
            '==|[A-Za-z0-9+/]{3}=|[A-Za-z0-9+/]{4})$')
        assert re.match(hexa_regexp, signature) is not None

    def test_load_private_key_raises_if_no_key_specified(self):
        with pytest.raises(ValueError):
            self.get_backend().load_private_key()

    def test_public_key_can_be_loaded_from_public_key_pem(self):
        signer = self.get_backend(public_key=self.vk_location)
        signer.load_public_key()

    def test_public_key_can_be_loaded_from_private_key_pem(self):
        signer = self.get_backend(private_key=self.sk_location)
        signer.load_public_key()

    def test_load_public_key_raises_an_error_if_missing_settings(self):
        with pytest.raises(ValueError) as excinfo:
            self.get_backend()
        msg = "Please, specify either a private_key or public_key location."
        assert str(excinfo.value) == msg

    @mock.patch('kinto_signer.signer.local_ecdsa.ECDSASigner')
    def test_load_from_settings(self, mocked_signer):
        local_ecdsa.load_from_settings({
            'signer.ecdsa.private_key': mock.sentinel.private_key,
            'signer.ecdsa.public_key': mock.sentinel.public_key,
        })

        mocked_signer.assert_called_with(
            private_key=mock.sentinel.private_key,
            public_key=mock.sentinel.public_key)

    def test_load_from_settings_fails_if_no_public_or_private_key(self):
        with pytest.raises(ValueError) as excinfo:
            local_ecdsa.load_from_settings({})
        msg = ("Please specify either kinto.signer.ecdsa.private_key or "
               "kinto.signer.ecdsa.public_key in the settings.")
        assert str(excinfo.value) == msg


class AutographSignerTest(unittest.TestCase):

    def setUp(self):
        self.signer = AutographSigner(
            hawk_id='alice',
            hawk_secret='fs5wgcer9qj819kfptdlp8gm227ewxnzvsuj9ztycsx08hfhzu',
            server_url='http://localhost:8000')

    @mock.patch('kinto_signer.signer.autograph.requests')
    def test_request_is_being_crafted_with_payload_as_input(self, requests):
        response = mock.MagicMock()
        response.json.return_value = [{"signature": SIGNATURE}]
        requests.post.return_value = response
        signature_bundle = self.signer.sign("test data")
        requests.post.assert_called_with(
            'http://localhost:8000/sign/data',
            auth=self.signer.auth,
            json=[{'hashwith': 'sha384', 'input': b'dGVzdCBkYXRh'}])
        assert signature_bundle['signature'] == SIGNATURE

    @mock.patch('kinto_signer.signer.autograph.AutographSigner')
    def test_load_from_settings(self, mocked_signer):
        autograph.load_from_settings({
            'signer.autograph.server_url': mock.sentinel.server_url,
            'signer.autograph.hawk_id': mock.sentinel.hawk_id,
            'signer.autograph.hawk_secret': mock.sentinel.hawk_secret,
        })

        mocked_signer.assert_called_with(
            server_url=mock.sentinel.server_url,
            hawk_id=mock.sentinel.hawk_id,
            hawk_secret=mock.sentinel.hawk_secret)
