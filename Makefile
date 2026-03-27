SPECFILE = chelon.spec
NAME = $(shell awk '/^Name:/ {print $$2; exit}' $(SPECFILE))
VERSION = $(shell awk '/^Version:/ {print $$2; exit}' $(SPECFILE))
RELEASE = $(shell awk '/^Release:/ {print $$2; exit}' $(SPECFILE) | sed 's/%{?dist}//g')

.PHONY: all help clean srpm rpm test-local

all: rpm

help:
	@echo "Chelon build targets:"
	@echo "  help        Show this help message"
	@echo "  srpm        Build source RPM"
	@echo "  rpm         Build binary RPM (default via 'all')"
	@echo "  clean       Remove local build artifacts"
	@echo "  test-local  Run Chelon service locally"

# Create SRPM
srpm:
	mkdir -p $(NAME)-$(VERSION)
	cp -r server tools systemd config README.md $(NAME)-$(VERSION)/
	tar czf $(NAME)-$(VERSION).tar.gz $(NAME)-$(VERSION)
	rm -rf $(NAME)-$(VERSION)
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

# Test the service locally (without RPM)
test-local:
	@echo "Starting Chelon service locally on port 5050..."
	@echo "Make sure GPG keys are imported first!"
	cd server && python3 chelon-service.py
