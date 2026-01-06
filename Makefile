NAME = chelon
VERSION = 1.0.0
RELEASE = 1

.PHONY: all clean srpm rpm

all: rpm

# Create source tarball
tarball:
	mkdir -p $(NAME)-$(VERSION)
	cp -r server tools systemd config README.md $(NAME)-$(VERSION)/
	tar czf $(NAME)-$(VERSION).tar.gz $(NAME)-$(VERSION)
	rm -rf $(NAME)-$(VERSION)

# Create SRPM
srpm: tarball
	mkdir -p ~/rpmbuild/{SOURCES,SPECS,SRPMS}
	cp $(NAME)-$(VERSION).tar.gz ~/rpmbuild/SOURCES/
	cp $(NAME).spec ~/rpmbuild/SPECS/
	rpmbuild -bs ~/rpmbuild/SPECS/$(NAME).spec

# Build RPM
rpm: srpm
	rpmbuild --rebuild ~/rpmbuild/SRPMS/$(NAME)-$(VERSION)-$(RELEASE)*.src.rpm

# Clean build artifacts
clean:
	rm -f $(NAME)-$(VERSION).tar.gz
	rm -rf $(NAME)-$(VERSION)
	rm -rf ~/rpmbuild/BUILD/$(NAME)-$(VERSION)
	rm -f ~/rpmbuild/RPMS/noarch/$(NAME)-$(VERSION)-$(RELEASE)*.rpm
	rm -f ~/rpmbuild/SRPMS/$(NAME)-$(VERSION)-$(RELEASE)*.src.rpm

# Install dependencies (Fedora 43)
deps:
	sudo dnf install -y \
		python3 \
		python3-flask \
		python3-gnupg \
		python3-pydantic \
		gnupg2 \
		rpm-build \
		systemd

# Test the service locally (without RPM)
test-local:
	@echo "Starting Chelon service locally on port 5050..."
	@echo "Make sure GPG keys are imported first!"
	cd server && python3 oracle-service.py
