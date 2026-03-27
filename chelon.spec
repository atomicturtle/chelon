Name:           chelon
Version:        1.2.0
Release:        3%{?dist}
Summary:        Remote GPG package signing service

License:        GPL-2.0-or-later
Vendor:         Atomicorp, Inc.
Packager:       Atomicorp, Inc.
URL:            https://www.atomicorp.com
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

%description
Chelon is a secure remote signing service for RPM packages and repository
metadata. Build servers send package hashes to Chelon via HTTPS API and
receive GPG signatures in response, eliminating the need for private keys on
build infrastructure.

This is a meta-package that can install both server and client components.

#
# Server subpackage
#
%package server
Summary:        Chelon signing service server
Requires:       python3
Requires:       python3-flask
Requires:       python3-gnupg
Requires:       python3-pydantic
Requires:       gnupg2
Requires:       systemd
Requires(pre):  shadow-utils

# Prevent auto-generated requires for user/group (we create them in %pre)
%global __requires_exclude ^(user|group)\\(chelon\\)$

Provides:       user(chelon)
Provides:       group(chelon)

%description server
Chelon signing service server component. This package contains the signing
service daemon, systemd unit, and admin tools for managing tokens and audit logs.

Install this package on the signing server (e.g., gamera).

#
# Client subpackage
#
%package client
Summary:        Chelon signing client tools
Requires:       python3

%description client
Chelon signing client tools. This package contains command-line tools for
signing RPM packages and repository metadata using a remote Chelon service.

Install this package on build servers and workstations that need to sign packages.

%prep
%setup -q

%build
# Nothing to build - pure Python

%install
# Create directory structure
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_datadir}/%{name}/server
install -d %{buildroot}%{_datadir}/%{name}/client
install -d %{buildroot}%{_sysconfdir}/%{name}
install -d %{buildroot}%{_unitdir}
install -d %{buildroot}%{_localstatedir}/lib/%{name}

# Install server files
install -m 755 server/chelon-service.py %{buildroot}%{_datadir}/%{name}/server/
install -m 644 server/signing_engine.py %{buildroot}%{_datadir}/%{name}/server/
install -m 644 server/auth.py %{buildroot}%{_datadir}/%{name}/server/
install -m 644 server/audit.py %{buildroot}%{_datadir}/%{name}/server/

# Install server admin tool
install -m 755 tools/chelon-admin %{buildroot}%{_bindir}/

# Install client tools
install -m 755 tools/chelon-sign %{buildroot}%{_bindir}/
install -d %{buildroot}%{python3_sitelib}
install -m 644 tools/chelon_client.py %{buildroot}%{python3_sitelib}/

# Install systemd unit
install -m 644 systemd/chelon.service %{buildroot}%{_unitdir}/

# Install default config
install -m 600 config/chelon.conf %{buildroot}%{_sysconfdir}/%{name}/

#
# Server scriptlets
#
%pre server
# Create chelon user if it doesn't exist
getent group chelon >/dev/null || groupadd -r chelon
getent passwd chelon >/dev/null || \
    useradd -r -g chelon -d %{_localstatedir}/lib/%{name} -s /sbin/nologin \
    -c "Chelon signing service" chelon
exit 0

%post server
%systemd_post chelon.service
# Fix ownership of data directory
chown -R chelon:chelon %{_localstatedir}/lib/%{name} 2>/dev/null || true

%preun server
%systemd_preun chelon.service

%postun server
%systemd_postun_with_restart chelon.service
# Only remove user if package is being erased (not upgraded)
if [ $1 -eq 0 ]; then
    userdel chelon 2>/dev/null || true
    groupdel chelon 2>/dev/null || true
fi

#
# File lists
#
%files server
%doc README.md
%{_datadir}/%{name}/server/
%{_bindir}/chelon-admin
%{_unitdir}/chelon.service
%attr(0750,root,chelon) %dir %{_sysconfdir}/%{name}
%attr(0600,chelon,chelon) %config(noreplace) %{_sysconfdir}/%{name}/chelon.conf
%attr(0750,chelon,chelon) %dir %{_localstatedir}/lib/%{name}

%files client
%doc README.md
%{_bindir}/chelon-sign
%{python3_sitelib}/chelon_client.py
%{python3_sitelib}/__pycache__/

%changelog
* Thu Mar 26 2026 Scott Shinn <support@atomicorp.com> - 1.2.0-3
- Increase chelon-sign client stdin size limit to 50MB
- Make client limit configurable via CHELON_MAX_INPUT_SIZE_BYTES

* Thu Mar 26 2026 Scott Shinn <support@atomicorp.com> - 1.2.0-1
- Make signing payload limit configurable via MAX_PAYLOAD_BYTES
- Increase default server-side payload limit to 50MB
- Improve payload limit error messages to include configured byte limits
- Add Makefile help target for common build/test commands

* Fri Jan 16 2026 Scott Shinn <support@atomicorp.com> - 1.1.0-2
- Generalize key management (remove hardcoded legacy/modern names)
- Support dynamic passphrase lookup SIGNING_KEY_<NAME>_PASSPHRASE
- Remove client-side hardcoded defaults

* Fri Jan 16 2026 Scott Shinn <support@atomicorp.com> - 1.1.0-1
- Add support for resolving signing keys by GPG Key ID
- Update chelon-sign to correctly parse -u <KEYID> in GPG emulation mode
- Improve SigningEngine to allow direct Key ID lookups

* Thu Jan 08 2026 Atomicorp <support@atomicorp.com> - 1.0.0-12
- Initial release
