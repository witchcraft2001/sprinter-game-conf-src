program bmp_extract;

{$APPTYPE CONSOLE}

uses
  SysUtils;


const
  RGB3 = 3;
  RGB4 = 4;

type

  BITMAPFILEHEADER = packed record
    bfType: word;
    bfSize: longint;
    bfReserved1: word;
    bfReserved2: word;
    bfOffBits: longint;
  end;

  BITMAPINFOHEADER = packed record
    biSize: longint;
    biWidth: longint;
    biHeight: longint;
    biPlanes: word;
    biBitCount: word;
    biCompression: longint;
    biSizeImage: longint;
    biXPelsPerMeter: longint;
    biYPelsPerMeter: longint;
    biClrUsed: longint;
    biClrImportant: longint;
  end;

  RGBQUAD = record
    rgbBlue: byte;
    rgbGreen: byte;
    rgbRed: byte;
    rgbReserved: byte;
  end;

procedure MsgHelp;
begin
  writeln('Usage:');
  writeln('       bmp_extract.exe <BMP FILE> <params> ...');
  writeln('<params>:');
  writeln('       /pn <file name> - output palette file-name');
  writeln('       /dn <file name> - output data file-name');
  writeln('       /pt <3 or 4> - palette type');
  writeln;
end;
procedure MsgWrong;
begin
  writeln('Unsupported BMP format');
  writeln('Accept only 128x72 px, 8-bit colors, no compression');
  writeln;
end;
procedure SavePalette(var buf: array of byte; fn: string; pal_type: longint);
var
  f: file of byte;
  i: longint;
  buf4: array [0..3] of byte;
begin
{$I-}
  AssignFile(f, fn);
  rewrite(f);

  case pal_type of

    RGB3:
      for i:= 0 to 255 do
      begin
        move(buf[i*4], buf4[0], 4);
        BlockWrite(f, buf4[0], 3);
      end;

    RGB4:
      BlockWrite(f, buf[0], length(buf));

  end;

  CloseFile(f);
{$I+}
  IOResult;
end;
procedure SaveBuf(var buf: array of byte; fn: string);
var
  f: file of byte;
begin
{$I-}
  AssignFile(f, fn);
  rewrite(f);
  BlockWrite(f, buf[0], length(buf));
  CloseFile(f);
{$I+}
  IOResult;
end;
function PalTypeToStr(t: longint): string;
begin
  case t of
    RGB3: result:= 'RGB3';
    RGB4: result:= 'RGB4';
    else result:= 'RGB unknown';
  end;
end;

var
  TFileHeader: BITMAPFILEHEADER;
  TInfoHeader: BITMAPINFOHEADER;
  f: file of byte;
  bmp_file_name, pal_file_name, dat_file_name: string;
  i: longint;
  pal_type: byte;
  buf: array of byte;
begin
  ExitCode:= 0;

  writeln('Extractor BMP-files for Sprinter BIOS logo');
  writeln('Copyright (c) 2022 Sprinter Team');

  // default params
  bmp_file_name:= 'logo.bmp';
  pal_file_name:= 'logo_pal.bin';
  dat_file_name:= 'logo_dat.bin';
  pal_type:= RGB4;

  if ParamStr(1) = '/?' then
  begin
    MsgHelp;
    exit;
  end;

  // override params
  if ParamStr(1) <> '' then
    bmp_file_name:= ParamStr(1);

  for i:= 2 to ParamCount do
  begin
    // palette file name
    if LowerCase(ParamStr(i)) = '/pn' then
      pal_file_name:= trim(ParamStr(i+1));

    // data file name
    if LowerCase(ParamStr(i)) = '/dn' then
      dat_file_name:= trim(ParamStr(i+1));

    if (LowerCase(ParamStr(i)) = '/pt') and (ParamStr(i+1) = '3') then
      pal_type:= RGB3;
  end;

  // ---------------------------------------------------------------------------

  AssignFile(f, bmp_file_name);

{$I-}
  Reset(f);
{$I+}
  i:= IOResult;
  if i <> 0 then
  begin
    writeln('IO error ', i, ' during open ['+bmp_file_name+'] file');
    MsgHelp;
    ExitCode:= 1;
    exit;
  end;

{$I-}
  BlockRead(f, TFileHeader, SizeOf(TFileHeader));
  BlockRead(f, TInfoHeader, SizeOf(TInfoHeader));
{$I+}
  i:= IOResult;
  if i <> 0 then
  begin
    writeln('IO error ', i, ' during open ['+bmp_file_name+'] file');
    ExitCode:= 1;
    exit;
  end;

//  writeln('FILE, ', SizeOf(TFileHeader));
//  writeln('bfType: ', TFileHeader.bfType);
//  writeln('bfSize: ', TFileHeader.bfSize);
//  writeln('bfReserved1: ', TFileHeader.bfReserved1);
//  writeln('bfReserved2: ', TFileHeader.bfReserved2);
//  writeln('bfOffBits: ', TFileHeader.bfOffBits);
//
//  writeln('INFO, ', SizeOf(TInfoHeader));
//  writeln('biSize: ', TInfoHeader.biSize);
//  writeln('biWidth: ', TInfoHeader.biWidth);
//  writeln('biHeight: ', TInfoHeader.biHeight);
//  writeln('biPlanes: ', TInfoHeader.biPlanes);
//  writeln('biBitCount: ', TInfoHeader.biBitCount);
//  writeln('biCompression: ', TInfoHeader.biCompression);
//  writeln('biSizeImage: ', TInfoHeader.biSizeImage);
//  writeln('biXPelsPerMeter: ', TInfoHeader.biXPelsPerMeter);
//  writeln('biYPelsPerMeter: ', TInfoHeader.biYPelsPerMeter);
//  writeln('biClrUsed: ', TInfoHeader.biClrUsed);
//  writeln('biClrImportant: ', TInfoHeader.biClrImportant);

  // check acceptable bmp format
  if (TFileHeader.bfType <> $4D42)
  or (TInfoHeader.biWidth <> 128)
  or (TInfoHeader.biHeight <> 72)
  or (TInfoHeader.biBitCount <> 8)
  or (TInfoHeader.biCompression <> 0)
  then
  begin
    MsgWrong;
    ExitCode:= 1;
    exit;
  end;

  with TInfoHeader do
    writeln('File ['+bmp_file_name+'], found ',biBitCount,' bit BMP ',biWidth,'x',biHeight,', output '+PalTypeToStr(pal_type)+' ['+pal_file_name+'] and ['+dat_file_name+']');

  // make palette
  SetLength(buf, 1024);
  FillChar(buf[0], length(buf), 0);
  BlockRead(f, buf[0], (TFileHeader.bfOffBits - SizeOf(TFileHeader) - SizeOf(TInfoHeader)) );
  SavePalette(buf, pal_file_name, pal_type);

  // make data
  SetLength(buf, TInfoHeader.biWidth * TInfoHeader.biHeight);
  FillChar(buf[0], length(buf), 0);
  BlockRead(f, buf[0], length(buf));
  SaveBuf(buf, dat_file_name);

  CloseFile(f);

  writeln('Done.');

end.
