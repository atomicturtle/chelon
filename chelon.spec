Name:           chelon
Version:        1.0.0
Release:        2%{?dist}
Summary:        Remote GPG package signing service (Chelon)

License:        GPL-2.0-or-later
Vendor:         Atomicorp, Inc.
Packager:       Atomicorp, Inc.
URL:            https://www.atomicorp.com
Source0:        %{name}-%{version}.tar.gz

BuildArch:      noarch

# Runtime dependencies (all from Fedora repos)
Requires:       python3
Requires:       python3-flask
Requires:       python3-gnupg
Requires:       python3-pydantic
Requires:       gnupg2
Requires:       systemd

# Needed for user/group creation in %pre
Requires(pre):  shadow-utils

# Prevent auto-generated requires for user/group (we create them in %pre)
%global __requires_exclude ^(user|group)\\(chelon\\)$

%description
Chelon is a secure remote signing service for RPM packages and repository
metadata. Build servers send package hashes to Chelon via HTTPS API and
receive GPG signatures in response, eliminating the need for private keys on
build infrastructure.

%prep
%setup -q

%build
# Nothing to build - pure Python

%install
# Create directory structure
install -d %{buildroot}%{_bindir}
install -d %{buildroot}%{_datadir}/%{name}/server
install -d %{buildroot}%{_sysconfdir}/%{name}
install -d %{buildroot}%{_unitdir}
install -d %{buildroot}%{_localstatedir}/lib/%{name}

# Install server files
install -m 755 server/chelon-service.py %{buildroot}%{_datadir}/%{name}/server/
install -m 644 server/signing_engine.py %{buildroot}%{_datadir}/%{name}/server/
install -m 644 server/auth.py %{buildroot}%{_datadir}/%{name}/server/
install -m 644 server/audit.py %{buildroot}%{_datadir}/%{name}/server/

# Install CLI tools
install -m 755 tools/chelon-admin %{buildroot}%{_bindir}/

# Install systemd unit
install -m 644 systemd/chelon.service %{buildroot}%{_unitdir}/

# Install default config
install -m 600 config/chelon.conf %{buildroot}%{_sysconfdir}/%{name}/

%pre
# Create chelon user if it doesn't exist
getent group chelon >/dev/null || groupadd -r chelon
getent passwd chelon >/dev/null || \
    useradd -r -g chelon -d %{_localstatedir}/lib/%{name} -s /sbin/nologin \
    -c "Chelon signing service" chelon
exit 0

%post
%systemd_post chelon.service
# Fix ownership of data directory
chown -R chelon:chelon %{_localstatedir}/lib/%{name} 2>/dev/null || true

%preun
%systemd_preun chelon.service

%postun
%systemd_postun_with_restart chelon.service

%files
%doc README.md
%{_datadir}/%{name}/
%{_bindir}/chelon-admin
%{_unitdir}/chelon.service
%config(noreplace) %{_sysconfdir}/%{name}/chelon.conf
%dir %{_localstatedir}/lib/%{name}

%changelog
* Tue Jan 06 2026 Atomicorp <support@atomicorp.com> - 1.0.0-1
- Initial release as Chelon
- Flask-based HTTP API for remote signing
- Support for Legacy and Modern GPG keys
- Token-based authentication
- Audit logging
- Default port: 5050
