program protect05;
{$R-}
{$APPTYPE CONSOLE}

uses
  Classes,
  SysUtils;

function GetFileSize(const FileName: String): Cardinal;
var
  AFile: File of Byte;
begin
  AssignFile(AFile, FileName);
  Reset(AFile);
  try
    Result := System.FileSize(AFile);
  finally
    CloseFile(AFile);
  end;
end;
procedure help;
begin
  writeln('Usage:');
  writeln('       protect05.exe <INPUT FILE>');
  writeln;
end;
function bit(const aValue: Cardinal; const BitPos: Byte): byte;
begin
  if ((aValue and (1 shl BitPos)) <> 0) then
    result:= 1
  else
    result:= 0;
end;

const
  MAX_BUF_SIZE = 1024 * 15;

var
  data_len: longint;
  o_file_name, i_file_name: string;
  o_file, i_file: file of byte;
  b,i, readed: longint;
  buf_in, buf_out: array of byte;
  CODE, D, D0_in, D0_out, todo: byte;
  unprotected: boolean;

begin
  writeln('PROTECT05: Sprinter-97 FW bitstream protector/decoder');
  writeln('Copyright (c) 2024 Sprinter Team');

  // check incoming values
  if ParamCount < 1 then
  begin
    help;
    exit;
  end;

  i_file_name:= ParamStr(1);
  if trim(i_file_name) = '' then
  begin
    writeln('ERROR: input file name is not specified');
    exit;
  end;

  // check buffer size
  data_len:= GetFileSize(i_file_name);
  if (data_len > MAX_BUF_SIZE) then
  begin
    writeln('ERROR: DATA_LENGTH='+inttostr(data_len)+', MAX_BUF_SIZE='+inttostr(MAX_BUF_SIZE));
    exit;
  end;

  // create buffers
  SetLength(buf_in, MAX_BUF_SIZE);
  FillChar(buf_in[0], length(buf_in), 0);

  SetLength(buf_out, MAX_BUF_SIZE);
  FillChar(buf_out[0], length(buf_out), 0);

  // load src file
{$I-}
  FileMode:= fmOpenRead;
  AssignFile(i_file, i_file_name);
  reset(i_file);
  seek(i_file, 0);
  BlockRead(i_file, buf_in[0], length(buf_in), readed);
  CloseFile(i_file);
{$I+}
  i:= IOResult;
  if (i > 0) then
  begin
    writeln('ERROR: IOResult='+inttostr(i)+' during loading input file. Readed '+inttostr(readed));
    exit;
  end;
  writeln('readed '+inttostr(readed)+' bytes');

  data_len:= readed;
  unprotected:= false;
  if (buf_in[0] = $FF) and (buf_in[1] = $FF) and (buf_in[2] = $62) and (buf_in[3] = $7B) then
    unprotected:= true;


  // protect / unprotect
  CODE:= 0;

  if unprotected then
    writeln('protecting ...')
  else
    writeln('decoding ...');

  for b:= 0 to data_len-1 do
  begin
    D:= buf_in[b];

    for i:= 0 to 7 do
    begin
      D0_in:= bit(D, i);

      D0_out:= bit(CODE,4) xor D0_in;
      buf_out[b]:= buf_out[b] or (D0_out shl i);

      if unprotected then
        todo:= D0_in // protect
      else
        todo:= D0_out; // unprotect

      CODE:= (CODE shl 1) or (bit(CODE,2) xor todo);

    end;

    // just header output
    if b < 8 then
      write(inttohex(buf_out[b])+' ');

  end;
  writeln;

  // write buffer to output file
  if unprotected then
    o_file_name:= ParamStr(1)+'.protected'
  else
    o_file_name:= ParamStr(1)+'.decoded';

{$I-}
  FileMode:= fmOpenReadWrite;
  AssignFile(o_file, o_file_name);
  reset(o_file);
  if IOResult <> 0 then
    rewrite(o_file);
  seek(o_file, 0);
  BlockWrite(o_file, buf_out[0], data_len);
  CloseFile(o_file);
{$I+}
  i:= IOResult;
  if (i > 0) then
  begin
    writeln('ERROR: IOResult='+inttostr(i)+' during writing to output file');
    exit;
  end;

  // finish
  writeln('');
end.
