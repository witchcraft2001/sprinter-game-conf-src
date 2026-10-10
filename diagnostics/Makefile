SJASMPLUS ?= sjasmplus
PYTHON ?= python3

all: build/GAMEDIAG.EXE

build/tiles.bin build/palettes.bin: make_assets.py
	$(PYTHON) make_assets.py

build/GAMEDIAG.EXE: game_diag.asm build/tiles.bin build/palettes.bin
	$(SJASMPLUS) --raw=$@ --lst=build/game_diag.lst --sym=build/game_diag.sym game_diag.asm

.PHONY: all
