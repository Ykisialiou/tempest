# Copyright (c) 2014 Deutsche Telekom AG
# Copyright (c) 2014 Hewlett-Packard Development Company, L.P.
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import abc

from oslo_log import log as logging
import six
from tempest_lib import auth

from tempest import config
from tempest import exceptions

CONF = config.CONF
LOG = logging.getLogger(__name__)

# Type of credentials available from configuration
CREDENTIAL_TYPES = {
    'identity_admin': ('identity', 'admin'),
    'user': ('identity', None),
    'alt_user': ('identity', 'alt')
}

DEFAULT_PARAMS = {
    'disable_ssl_certificate_validation':
        CONF.identity.disable_ssl_certificate_validation,
    'ca_certs': CONF.identity.ca_certificates_file,
    'trace_requests': CONF.debug.trace_requests
}


# Read credentials from configuration, builds a Credentials object
# based on the specified or configured version
def get_configured_credentials(credential_type, fill_in=True,
                               identity_version=None):
    identity_version = identity_version or CONF.identity.auth_version
    if identity_version not in ('v2', 'v3'):
        raise exceptions.InvalidConfiguration(
            'Unsupported auth version: %s' % identity_version)
    if credential_type not in CREDENTIAL_TYPES:
        raise exceptions.InvalidCredentials()
    conf_attributes = ['username', 'password', 'tenant_name']
    if identity_version == 'v3':
        conf_attributes.append('domain_name')
    # Read the parts of credentials from config
    params = DEFAULT_PARAMS.copy()
    section, prefix = CREDENTIAL_TYPES[credential_type]
    for attr in conf_attributes:
        _section = getattr(CONF, section)
        if prefix is None:
            params[attr] = getattr(_section, attr)
        else:
            params[attr] = getattr(_section, prefix + "_" + attr)
    # Build and validate credentials. We are reading configured credentials,
    # so validate them even if fill_in is False
    credentials = get_credentials(fill_in=fill_in,
                                  identity_version=identity_version, **params)
    if not fill_in:
        if not credentials.is_valid():
            msg = ("The %s credentials are incorrectly set in the config file."
                   " Double check that all required values are assigned" %
                   credential_type)
            raise exceptions.InvalidConfiguration(msg)
    return credentials


# Wrapper around auth.get_credentials to use the configured identity version
# is none is specified
def get_credentials(fill_in=True, identity_version=None, **kwargs):
    params = dict(DEFAULT_PARAMS, **kwargs)
    identity_version = identity_version or CONF.identity.auth_version
    # In case of "v3" add the domain from config if not specified
    if identity_version == 'v3':
        domain_fields = set(x for x in auth.KeystoneV3Credentials.ATTRIBUTES
                            if 'domain' in x)
        if not domain_fields.intersection(kwargs.keys()):
            # TODO(andreaf) It might be better here to use a dedicated config
            # option such as CONF.auth.tenant_isolation_domain_name
            params['user_domain_name'] = CONF.identity.admin_domain_name
        auth_url = CONF.identity.uri_v3
    else:
        auth_url = CONF.identity.uri
    return auth.get_credentials(auth_url,
                                fill_in=fill_in,
                                identity_version=identity_version,
                                **params)


@six.add_metaclass(abc.ABCMeta)
class CredentialProvider(object):
    def __init__(self, identity_version=None, name=None, password='pass',
                 network_resources=None):
        """A CredentialProvider supplies credentials to test classes.
        :param identity_version If specified it will return credentials of the
                                corresponding identity version, otherwise it
                                uses auth_version from configuration
        :param name Name of the calling test. Included in provisioned
                    credentials when credentials are provisioned on the fly
        :param password Used for provisioned credentials when credentials are
                        provisioned on the fly
        :param network_resources Network resources required for the credentials
        """
        # TODO(andreaf) name and password are tenant isolation specific, and
        # could be removed from this abstract class
        self.name = name or "test_creds"
        self.identity_version = identity_version or CONF.identity.auth_version
        if not auth.is_identity_version_supported(self.identity_version):
            raise exceptions.InvalidIdentityVersion(
                identity_version=self.identity_version)

    @abc.abstractmethod
    def get_primary_creds(self):
        return

    @abc.abstractmethod
    def get_admin_creds(self):
        return

    @abc.abstractmethod
    def get_alt_creds(self):
        return

    @abc.abstractmethod
    def clear_isolated_creds(self):
        return

    @abc.abstractmethod
    def is_multi_user(self):
        return

    @abc.abstractmethod
    def is_multi_tenant(self):
        return

    @abc.abstractmethod
    def get_creds_by_roles(self, roles, force_new=False):
        return

    @abc.abstractmethod
    def is_role_available(self, role):
        return


class TestResources(object):
    """Readonly Credentials, with network resources added."""

    def __init__(self, credentials):
        self._credentials = credentials
        self.network = None
        self.subnet = None
        self.router = None

    def __getattr__(self, item):
        return getattr(self._credentials, item)

    def set_resources(self, **kwargs):
        for key in kwargs.keys():
            if hasattr(self, key):
                setattr(self, key, kwargs[key])

    @property
    def credentials(self):
        return self._credentials
