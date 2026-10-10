program disk3;

{$APPTYPE CONSOLE}

uses
  Classes,
  SysUtils;

function vall(s: string): longint;
begin
  try
    result:= strtoint(s);
  except
    result:= 0;
  end;
end;
function strr(n: longint): string;
begin
  try
    result:= inttostr(n);
  except
    result:= '0';
  end;
end;
procedure SplitParams(const splitter: string; const params: string; var dest: TStringList);
var
  p: longint;
  tmp: string;
begin
  if not Assigned(dest) then 
    exit;

  dest.Clear;
  tmp:= params;
  p:= pos(splitter, tmp);

  while (p > 0) do
  begin
    dest.Add(copy(tmp, 1, p-1));
    tmp:= copy(tmp, p+1, length(tmp) - p);
    p:= pos(splitter, tmp);
  end;
  dest.Add(tmp);
end;

procedure help;
begin
  writeln('DISK3: Sprinter FW builder');
  writeln('Copyright (c) 2021 Sprinter Team');
  writeln('Usage:');
  writeln('       disk3.exe <OUTPUT FILE> <INPUT FILE> <OUTPUT_OFFSET, DATA_LENGTH, INPUT_OFFSET>');
  writeln('Offsets and data length could be in dec or hex values: 16384 or 4000H');
  writeln;
end;

const
  MAX_BUF_SIZE = 1024 * 512;

var
  items_list: TStringList;
  s: string;
  o_ofs, data_len, i_ofs: longint;
  o_file_name, i_file_name: string;
  o_file, i_file: file of byte;
  i, readed: longint;

  buf: array of byte;

begin
//  DISK3.COM   OUTPUT_FILE   INPUT_FILE   OUTPUT_OFFSET,LENGHT,INPUT_OFFSET

  // check incoming values
  if ParamCount < 3 then
  begin
    help;
    exit;
  end;

  o_file_name:= ParamStr(1);
  if trim(o_file_name) = '' then
  begin
    writeln('ERROR: output file name is not specified');
    exit;
  end;

  i_file_name:= ParamStr(2);
  if trim(o_file_name) = '' then
  begin
    writeln('ERROR: input file name is not specified');
    exit;
  end;

  // parse offsets
  items_list:= TStringList.Create;

  SplitParams(',', ParamStr(3), items_list);

  s:= '0';
  if items_list.Count >= 1 then
    s:= items_list[0];
  if UpperCase(s[length(s)]) = 'H' then
    s:= '$' + copy(s, 1, length(s)-1);
  o_ofs:= vall(s);

  s:= '0';
  if items_list.Count >= 2 then
    s:= items_list[1];
  if UpperCase(s[length(s)]) = 'H' then
    s:= '$' + copy(s, 1, length(s)-1);
  data_len:= vall(s);

  s:= '0';
  if items_list.Count >= 3 then
    s:= items_list[2];
  if UpperCase(s[length(s)]) = 'H' then
    s:= '$' + copy(s, 1, length(s)-1);
  i_ofs:= vall(s);

  items_list.Free;

  // work params
  write('<'+o_file_name+'> <'+i_file_name+'> <'+inttohex(o_ofs,1)+'h, '+inttohex(data_len,1)+'h, '+inttohex(i_ofs,1)+'h>');

  // check buffer size
  if (data_len > MAX_BUF_SIZE) then
  begin
    writeln('ERROR: DATA_LENGTH='+strr(data_len)+', MAX_BUF_SIZE='+strr(MAX_BUF_SIZE));
    exit;
  end;

  // create new buffer
  SetLength(buf, MAX_BUF_SIZE);
  FillChar(buf[0], length(buf), $FF);

  // load src file
{$I-}
  FileMode:= fmOpenRead;
  AssignFile(i_file, i_file_name);
  reset(i_file);
  Seek(i_file, i_ofs);
  BlockRead(i_file, buf[0], data_len, readed);
  CloseFile(i_file);
{$I+}
  i:= IOResult;
  if (i > 0) then
  begin
    writeln('ERROR: IOResult='+strr(i)+' during loading input file. Readed '+inttohex(readed,1)+'h');
    exit;
  end;
  write(', readed '+inttohex(readed,1)+'h');

  // write buffer to output file
{$I-}
  FileMode:= fmOpenReadWrite;
  AssignFile(o_file, o_file_name);
  reset(o_file);
  if IOResult <> 0 then
    rewrite(o_file);
  Seek(o_file, o_ofs);
  BlockWrite(o_file, buf[0], data_len);
  CloseFile(o_file);
{$I+}
  i:= IOResult;
  if (i > 0) then
  begin
    writeln('ERROR: IOResult='+strr(i)+' during writing to output file');
    exit;
  end;

  // finish
  writeln(', OK');
end.
