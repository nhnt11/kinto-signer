from cliquet.events import ResourceChanged

from kinto_signer import signer as signer_module
from kinto_signer.updater import RemoteUpdater
import kinto_client


def includeme(config):
    # Process settings to remove storage wording.
    settings = config.get_settings()

    expected_bucket = settings.get('kinto_signer.bucket')
    expected_collection = settings.get('kinto_signer.collection')

    priv_key = settings.get('kinto_signer.private_key')
    config.registry.signer = signer_module.ECDSABackend(
        {'private_key': priv_key})

    remote_url = settings['kinto_signer.remote_server_url']

    auth = settings.get('kinto_signer.remote_server_auth', None)
    if auth is not None:
        auth = tuple(auth.split(':'))
    remote = kinto_client.Client(server_url=remote_url, bucket=expected_bucket,
                                 collection=expected_collection,
                                 auth=auth)

    def on_resource_changed(event):
        payload = event.payload
        resource_name = payload['resource_name']
        action = payload['action']

        # XXX Replace the filtering by events predicates (on the next Kinto
        # release)
        # XXX Add a concept of local and remote buckets/collections
        correct_bucket = True  # payload.get('bucket_id') == expected_bucket
        correct_coll = payload.get('collection_id') == expected_collection
        is_coll = resource_name == 'collection'
        is_creation = action in ('create', 'update')

        if not (correct_coll and correct_bucket):
            return
        if not (is_creation and is_coll):
            return

        should_sign = any([True for r in event.impacted_records
                           if r['new'].get('status') == 'to-sign'])
        if should_sign:
            registry = event.request.registry
            updater = RemoteUpdater(
                remote=remote,
                signer=registry.signer,
                storage=registry.storage,
                bucket_id=event.payload['bucket_id'],
                collection_id=event.payload['collection_id'])

            updater.sign_and_update_remote()

    config.add_subscriber(on_resource_changed, ResourceChanged)
