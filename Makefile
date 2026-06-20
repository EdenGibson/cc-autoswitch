.PHONY: test dry-run install

test:
	python3 -m unittest test_cc_autoswitch -v

dry-run:
	python3 cc_autoswitch.py --dry-run

install:
	./install.sh
