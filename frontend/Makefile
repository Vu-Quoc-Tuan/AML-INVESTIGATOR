# Thin wrapper: Docker targets live in the monorepo root Makefile.
ROOT := $(abspath ..)

.PHONY: up down build logs ps rebuild restart down-clean

up down build logs ps rebuild restart down-clean:
	$(MAKE) -C $(ROOT) $@
