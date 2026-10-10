; GAME_K50 hardware diagnostic. sjasmplus; code + stack remain in window 2.
; Loads external K50.ACX through DSS/BIOS, uses no DSS video calls afterwards.
; Keys (ZX keyboard matrix): 1=X+1, 2=Y+1, 3=page, 4=zero, Q=ROM hard reset.
        ORG 0
        DB "EXE",1
        DD 512
        DW 0,0,0,0,08100h,08100h,0BFFFh
        DS 512-$,0
        DISP 08100h
start:
        LD C,0
        RST 10h                 ; DSS version: DE=version/mod, BC=build
        LD HL,0146h             ; 1.70, build >= 998
        OR A
        SBC HL,DE
        JP C,version_ok
        JP NZ,error
        LD HL,997
        OR A
        SBC HL,BC
        JP NC,error
version_ok:
        LD HL,name
        LD A,1
        LD C,11h
        RST 10h
        JP C,error
        LD (handle),A
        LD BC,0215h             ; seek to end: HL:IX = file length
        LD HL,0
        LD IX,0
        RST 10h
        JP C,error
        LD A,H
        OR A
        JP NZ,error
        LD A,L
        CP 2
        JP NC,error
        OR A
        JR Z,small_size
        LD A,IXH
        OR IXL
        JP NZ,error             ; >65536
        JR size_ok
small_size:
        LD A,IXH
        OR A
        JR NZ,size_ok
        LD A,IXL
        CP 7
        JP C,error              ; compressed header requires a zero-run count
size_ok:
        LD (file_size_hi),HL
        LD (file_size),IX
        LD (remaining_hi),HL
        LD (remaining),IX
        LD A,(handle)
        LD BC,0015h
        LD HL,0
        LD IX,0
        RST 10h
        JP C,error
        ; Allocate exactly ceil(size/16K), so the BIOS walks only ACX pages.
        LD HL,(remaining_hi)
        LD A,L
        OR A
        LD A,4
        JR NZ,page_count_ready
        LD HL,(remaining)
        DEC HL
        LD A,H
        RLCA
        RLCA
        AND 3
        INC A
page_count_ready:
        LD (pages_used),A
        LD B,A
        LD C,3Dh
        RST 10h
        JP C,error
        LD (block),A
        LD HL,pages
        LD C,0C5h
        RST 08h
        JP C,error
        LD A,(pages_used)
        CP B
        JP NZ,error
load_page:
        LD A,(page_index)
        LD E,A
        LD D,0
        LD HL,pages
        ADD HL,DE
        LD A,(HL)
        OUT (0E2h),A
        LD HL,0C000h
        LD DE,0C001h
        LD BC,03FFFh
        LD (HL),0FFh            ; BIOS accepts final-page FF padding
        LDIR
        LD DE,04000h
        LD HL,(remaining_hi)
        LD A,H
        OR L
        JR NZ,read_page
        LD HL,(remaining)
        LD A,H
        OR L
        JR Z,next_page
        OR A
        SBC HL,DE
        JR NC,read_page
        LD DE,(remaining)
read_page:
        PUSH DE
        LD A,(handle)
        LD HL,0C000h
        LD C,13h
        RST 10h
        POP DE                  ; restore request; DSS.Read DE is unspecified
        JP C,error
        LD HL,(remaining)
        OR A
        SBC HL,DE
        LD (remaining),HL
        LD HL,(remaining_hi)
        LD DE,0
        SBC HL,DE
        LD (remaining_hi),HL
next_page:
        LD A,(page_index)
        INC A
        LD (page_index),A
        LD HL,pages_used
        CP (HL)
        JR NZ,load_page
        ; Confirm total bytes consumed through the documented file-position API.
        ; Read may report EOF in A with carry clear; no returned DE is assumed.
        LD A,(handle)
        LD BC,0115h             ; current position + zero
        LD HL,0
        LD IX,0
        RST 10h
        JP C,error
        LD DE,(file_size_hi)
        OR A
        SBC HL,DE
        JP NZ,error
        PUSH IX
        POP HL
        LD DE,(file_size)
        OR A
        SBC HL,DE
        JP NZ,error
        LD A,(handle)
        LD C,12h
        RST 10h
        ; Reconfiguration is authorized only for a K50 bitstream. Compressed
        ; K50 prefix is FF FF 62 7B 3C 00, followed by a nonzero run count.
        LD A,(pages)
        OUT (0E2h),A
        LD HL,0C000h
        LD DE,k50_prefix
        LD B,6
check_prefix:
        LD A,(DE)
        CP (HL)
        JP NZ,error
        INC HL
        INC DE
        DJNZ check_prefix
        LD A,(HL)
        OR A
        JP Z,error              ; first zero run may extend beyond header
        LD A,(block)
        LD B,A
        LD A,0FEh
        LD C,0F3h
        RST 08h                 ; AcexSetUpNow; requires compatible BIOS
        JP C,error
        DI
        LD A,4
        OUT (03Ch),A            ; fast RAM off
        LD A,0C0h
        OUT (089h),A
        LD A,050h
        OUT (0E2h),A            ; VRAM through window 3 + PORT_Y
        LD A,1
        OUT (0C3h),A            ; graphics addressing, Spectrum emulation off
        XOR A
        OUT (0C9h),A
        ; Palette: RGB triplets for eight groups, all 256 byte indices.
        LD HL,palettes
        XOR A
palette_line:
        OUT (089h),A
        PUSH AF
        LD DE,0C3E0h
        LD BC,32
        LDIR
        POP AF
        INC A
        JR NZ,palette_line
        ; Eight graphics rows at Y=128..135, X=0..447.
        LD HL,tiles
        LD A,128
graphics_line:
        OUT (089h),A
        PUSH AF
        LD DE,0C000h
        LD BC,448
        LDIR
        POP AF
        INC A
        CP 136
        JR NZ,graphics_line
        CALL maps
poll:
        LD BC,0FBFEh            ; Q W E R T
        IN A,(C)
        BIT 0,A
        JP Z,reset
        LD BC,0F7FEh            ; 1 2 3 4 5
        IN A,(C)
        AND 15
        CP 15
        JR Z,poll
        LD B,A
        BIT 0,B
        JR NZ,no_x
        LD A,(scroll)
        INC A
        AND 15
        LD C,A
        LD A,(scroll)
        AND 0F0h
        OR C
        LD (scroll),A
no_x:
        BIT 1,B
        JR NZ,no_y
        LD A,(scroll)
        ADD A,16
        LD (scroll),A
no_y:
        BIT 2,B
        JR NZ,no_page
        LD A,(display_page)
        XOR 1
        LD (display_page),A
        OUT (0C9h),A
no_page:
        BIT 3,B
        JR NZ,no_zero
        XOR A
        LD (scroll),A
no_zero:
        CALL maps
release:
        LD BC,0F7FEh
        IN A,(C)
        AND 15
        CP 15
        JR NZ,release
        JR poll
; All 56 columns and 40 rows, both descriptor pages. MODE3 at column 53
; tests controls beyond visible X=320. Page 1 reverses cell numbering.
maps:
        LD D,0                  ; descriptor column
column:
        LD A,D
        ADD A,A
        INC A
        OUT (089h),A
        LD HL,0C300h
        LD E,0                  ; row
row:
        LD A,E
        CP 32
        LD A,0FCh
        JR NC,control
        LD A,D
        AND 63
        CP 40
        LD A,0F4h
        JR NC,control
        LD A,E
        AND 3
        RRCA
        RRCA                    ; four palettes; byte graphics also with bit5=0
        JR write_mode
control:
        LD C,A
        LD A,D
        AND 63
        CP 53
        LD A,C
        JR NZ,not_scroll
        LD A,0F4h
not_scroll:
        LD C,A
        LD A,E
        CP 39
        LD A,C
        JR NZ,write_mode
        OR 1                    ; interrupt during final blank row
write_mode:
        LD C,A
        LD A,D
        AND 63
        BIT 6,D
        JR Z,normal_number
        LD B,A
        LD A,55
        SUB B
normal_number:
        LD B,0
        ADD A,A
        RL B
        ADD A,A
        RL B
        ADD A,A
        RL B                    ; B:A = tile X
        PUSH AF
        LD A,C
        CP 0E0h
        JR NC,store_mode        ; control low bits encode IRQ, not graphics X
        OR B
store_mode:
        LD (HL),A
        INC HL
        POP AF
        LD (HL),A
        INC HL
        LD (HL),128
        INC HL
        LD A,(scroll)
        LD (HL),A
        INC HL
        INC E
        LD A,E
        CP 40
        JR NZ,row
        INC D
        LD A,D
        CP 56
        JR NZ,not_page_end
        LD D,64
not_page_end:
        LD A,D
        CP 120
        JP NZ,column
        LD A,0C0h
        OUT (089h),A
        RET
reset:
        LD BC,03FDh             ; hard reset restores standard ROM config
        JP 18h
error:
        LD HL,message
        LD C,05Ch
        RST 10h
        LD BC,0FF41h
        LD A,0FFh
        RST 10h
        JR $
name:           DB "K50.ACX",0
message:        DB "GAME DIAG: DSS/ACX/BIOS setup error",13,10,0
k50_prefix:     DB 255,255,98,123,60,0
handle:         DB 0
block:          DB 0
page_index:     DB 0
pages_used:     DB 0
file_size:      DW 0
file_size_hi:   DW 0
remaining:      DW 0
remaining_hi:   DW 0
pages:          DS 256,0       ; BIOS #C5 writes pages PLUS FF terminator
scroll:         DB 0
display_page:   DB 0
tiles:          INCBIN "build/tiles.bin"
palettes:       INCBIN "build/palettes.bin"
        ASSERT $ < 0BE00h
        ENT
