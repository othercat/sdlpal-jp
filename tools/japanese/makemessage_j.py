#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import with_statement

import argparse
import os
import traceback
import struct
import sys
import binascii
import re

if sys.version_info[0] >= 3:
    # Python 3 环境
    def to_str(b, enc='utf-8'): return b.decode(enc, 'replace') if isinstance(b, bytes) else b
    def to_bytes(s, enc='utf-8'): return s.encode(enc) if isinstance(s, str) else s
else:
    # Python 2 环境
    def to_str(b, enc='utf-8'): return b
    def to_bytes(s, enc='utf-8'): return s

def crc32(buf):
    return hex(binascii.crc32(buf) & 0xFFFFFFFF)

def main():

    parser = argparse.ArgumentParser(description = 'Generate a translatable language file that can be used by SDLPAL.')
    parser.add_argument('gamepath', help = 'PC game path where SSS.MKF & M.MSG & WORD.DAT are located.')
    parser.add_argument('saturnpath', help = 'Saturn game path where JM.SEC & JM.NOR & PROG.BIN & JM.MSG are located.')
    parser.add_argument('outputfile', help = 'Path of the output message file.')
    parser.add_argument('pcencoding', choices = ['gbk', 'big5'], help = 'Text encoding name of the PC version, should be either gbk or big5.')
    # parser.add_argument('encoding', choices = ['gbk', 'big5', 'shift_jis'], help = 'Text encoding name, should be either gbk or big5 or shift_jis.')
    # parser.add_argument('-w', '--width', dest = 'wordwidth', default = 16, type = int, help = 'Word width in bytes, default is 16')
    # parser.add_argument("-c", "--comment", action = 'store_false', help = 'Automatically generate comments')
    parser.add_argument("-d", "--debug", action = 'store_true', help = 'Debug mode')
    options = parser.parse_args()

    options.encoding = "shift_jis"
    options.wordwidth = 16
    options.comment = True

    if options.gamepath[-1] != '/' and options.gamepath[-1] != '\\':
        options.gamepath += '/'
    if options.saturnpath[-1] != '/' and options.saturnpath[-1] != '\\':
        options.saturnpath += '/'

    script_bytes = []
    index_bytes = []
    msg_bytes = []
    word_bytes = []
    sss_bytes = []

    jdata_bytes = []
    jscript_bytes = []

    msg_begin =0

    is_msg_group = 0    #是否正在处理文字组的标示。
    jis_msg_group = 0

    jscript_bytes = []
    jexscript_bytes = []
    jindex_bytes = []
    jmsg_bytes = []
    jword_bytes = []

    msg_count = 0
    last_index = -1
    temp = ""
    jtemp = ""
    comment = ""
    message = ""
    jmessage = ""


    version = "2026.08"
    slf_version = "3.1"

    cmd_extstr = ""

    # if options.comment: cmd_extstr += "-c"
    if options.debug: cmd_extstr += " -d"

    output = "# SDLPAL localization file\n"
    output += "# Version %s\n" % (slf_version)
    output += "# This document is generated with MakeMessage J Utility ver. %s\n" % (version)
    output += "# Please visit https://github.com/sdlpal/sdlpal/ for more information.\n\n"
	
    output += "# Command line: makemessage_j.py PATH/TO/THE/GAME/DIRECTORY/ PATH/OF/THE/GENERATED/FILE %s %s\n\n" % (options.pcencoding, cmd_extstr)
	

    print ("MakeMessage Utility by SDLPal Team ver. %s" % (version))
    print ("Python 3 adaption by PalAlexx, OPL3ChipFan and Palxex")
    if sys.version_info.major < 3:
        print ("Running in Python 2 compability mode. Python 3 is recommended.")	
    print ("Now Processing, Please wait...")

    for file_ in os.listdir(options.gamepath):
        if file_.lower() == 'sss.mkf':
            try:
                with open(options.gamepath + file_, 'rb') as f:
                    f.seek(12, os.SEEK_SET)
                    offset_begin, script_begin, file_end = struct.unpack('<III', f.read(12))
                    f.seek(offset_begin, os.SEEK_SET)
                    index_bytes = f.read(script_begin - offset_begin)
                    script_bytes = f.read(file_end - script_begin)

                    f.seek(0, os.SEEK_SET)
                    sss_bytes = f.read()
            except:
                traceback.print_exc()
                return
        elif file_.lower() == 'm.msg':
            try:
                with open(options.gamepath + file_, 'rb') as f:
                    msg_bytes = f.read()
            except:
                traceback.print_exc()
                return
        elif file_.lower() == 'word.dat':
            try:
                with open(options.gamepath + file_, 'rb') as f:
                    data_bytes = f.read()
            except:
                traceback.print_exc()
                return

    for file_ in os.listdir(options.saturnpath):
        if file_.lower() == 'jm.sec':
            try:
                with open(options.saturnpath + file_, 'rb') as f:
                    jscript_bytes=f.read()
            except:
                traceback.print_exc()
                return
        elif file_.lower() == 'jm.nor':
            try:
                with open(options.saturnpath + file_, 'rb') as f:
                    jexscript_bytes=f.read()
            except:
                traceback.print_exc()
                return
        elif file_.lower() == 'prog.bin':
            try:
                with open(options.saturnpath + file_, 'rb') as f:
                    jdata_bytes = f.read()
                    jdata_bytes = jdata_bytes[358868:393211+1]
                    #将文字索引部分从PROG.BIN中提取出来，地址：0x579D4~0x5FFFB

                    bin_output=[]
                    jmsg_begin_last=0
                    #记录上一次msg_begin地址。用于判断是否跨越FF FF。
                    ffff_times=0
                    #记录跨越了几次FF FF。
                    
                    for i in range(0,(len(jdata_bytes) // 2 - 1 + 1)):
                        jmsg_begin = struct.unpack(">H",jdata_bytes[i*2:i*2+2])[0]
                        jmsg_begin = jmsg_begin + 65536 * ffff_times
                        #处理跨越FF FF的问题。
                        
                        if jmsg_begin < jmsg_begin_last:
                            ffff_times = ffff_times + 1
                            jmsg_begin = jmsg_begin + 65536
                            #如果本次的地址小于上次获得的地址，那么就说明又跨了一次。

                        jmsg_begin_last = jmsg_begin
                        #判断完毕，msg_begin_last更新值。

                        bin_output = bin_output+list(struct.pack("<I",jmsg_begin))
                        #print len(bin_output)

                        jindex_bytes = bytearray(bin_output)



            except:
                traceback.print_exc()
            try:
                with open(options.saturnpath + file_, 'rb') as f:
                    jword_bytes = f.read()
                    jword_bytes = jword_bytes[401220:410275+1]
                    #将WORD部分从PROG.BIN中提取出来，地址：0x61F44~0x642A3
            except:
                traceback.print_exc()
                return
        elif file_.lower() == 'jm.msg':
            try:
                with open(options.saturnpath + file_, 'rb') as f:
                    jmsg_bytes = f.read()

                    if sys.version_info[0] >= 3:
                    # Python 3 treats bytes as integers during iteration
                        jmsg_bytes = bytes([x for x in jmsg_bytes if x != 0])
                    else:
                        jmsg_bytes=filter(lambda x:x !='\x00', jmsg_bytes)
                        #去除SS版*M.MSG中的空白。http://gmingzhe.blog.51cto.com/810664/165905

                    jmsg_bytes = bytearray(jmsg_bytes)
            except:
                traceback.print_exc()
                return
    jscript_bytes += jexscript_bytes
    #将SS版两部分脚本结合起来。
    if options.debug:
        try:
            with open("sss4.bin", 'wb') as f:
                f.write(bytearray(script_bytes))
            with open("index.bin","wb") as f:
                f.write(index_bytes)
            with open("jscript.bin", 'wb') as f:
                f.write(bytearray(jscript_bytes))
            with open("jindex.bin","wb") as f:
                f.write(bytearray(jindex_bytes))
            with open("jword.bin","wb") as f:
                f.write(bytearray(jword_bytes))
            #with open("jindex.bin","wb") as f:
                #f.write(jindex_bytes)
        except:
            traceback.print_exc()
            return

    output += "# CRC32 of the resource files:\n"
    output += "# SSS.MKF:   %s\n" % (crc32(sss_bytes))
    output += "# M.MSG:     %s\n" % (crc32(msg_bytes))
    output += "# WORD.DAT:  %s\n" % (crc32(data_bytes))
    output += "# \n"
    output += "# JM.SEC:    %s\n" % (crc32(jscript_bytes))
    output += "# JM.NOR:    %s\n" % (crc32(jexscript_bytes))
    output += "# PROG.BIN:  %s\n" % (crc32(jdata_bytes))
    output += "# JM.MSG:    %s\n" % (crc32(jexscript_bytes))
    output += "# \n"

    if len(data_bytes) % options.wordwidth != 0:
        padding = b'\x20' * (
            options.wordwidth -
            len(data_bytes) % options.wordwidth
        )
        data_bytes += padding

    output += "# All lines, except those inside [BEIGN MESSAGE] and [END MESSAGE], can be commented by adding the sharp '#' mark at the first of the line.\n\n"

    output += "# This section contains the information that will be displayed when a user finishes the game.\n"
    output += "# Only the keys listed here are valid. Other keys will be ignored.\n"
    output += "[BEGIN CREDITS]\n"
    output += "# Place the translated text of 'Classical special build' here in no more than 24 half-wide characters.\n"
    output += "1= Classical special build\n"
    output += "# Place the translated porting information template at the following two lines. Be aware that each replaced line will be truncated into at most 40 half-wide characters.\n"
    output += "6= ${platform} port by ${author}, ${year}.\n"
    output += "7=\n"
    output += "# Place the translated GNU licensing information at the following three lines. Be aware that each line will be truncated into at most 40 half-wide characters.\n"
    output += "8=   This is a free software and it is\n"
    output += "9=   published under GNU General Public\n"
    output += "10=    License v3.\n"
    output += "# Place the translated text at the following line. Be aware that each line will be truncated into at most 40 half-wide characters.\n"
    output += "11=    ...Press Enter to continue\n"
    output += "[END CREDITS]\n\n"

    output += "# Each line controls one position value.\n"
    output += "# For each line, the format is 'idx=x,y,flag', while the flag is optional\n"
    output += "# If bit 0 of flag is 1, then use 8x8 font; and while bit 1 of flag is 1, then disable shadow\n"
    output += "# Lines from 1 to 26 are for equipping screen, lines from 27 to 80 are for status screen.\n"
    output += "[BEGIN LAYOUT]\n"
    output += "# 1 is the position of image box in equipping screen\n"
    output += "1=8,8\n"
    output += "# 2 is the position of role list box in equipping screen\n"
    output += "2=2,95\n"
    output += "# 3 is the position of current equipment's name in equipping screen\n"
    output += "3=5,70\n"
    output += "# 4 is the position of current equipment's amount in equipping screen\n"
    output += "4=51,57\n"
    output += "# 5 .. 10 are the positions of words 600 ... 605 in equipping screen\n"
    output += "5=92,11\n"
    output += "6=92,33\n"
    output += "7=92,55\n"
    output += "8=92,77\n"
    output += "9=92,99\n"
    output += "10=92,121\n"
    output += "# 11 .. 16 are the positions of equipped equipments in equipping screen\n"
    output += "11=130,11\n"
    output += "12=130,33\n"
    output += "13=130,55\n"
    output += "14=130,77\n"
    output += "15=130,99\n"
    output += "16=130,121\n"
    output += "# 17 .. 21 are the positions of words 51 ... 55 in equipping screen\n"
    output += "17=226,10\n"
    output += "18=226,32\n"
    output += "19=226,54\n"
    output += "20=226,76\n"
    output += "21=226,98\n"
    output += "# 22 .. 26 are the positions of status values in equipping screen\n"
    output += "22=260,14\n"
    output += "23=260,36\n"
    output += "24=260,58\n"
    output += "25=260,80\n"
    output += "26=260,102\n"
    output += "# 27 is the position of role name in status screen\n"
    output += "27=110,8\n"
    output += "# 28 is the position of role image in status screen\n"
    output += "28=110,30\n"
    output += "# 29 is the position of EXP label in status screen\n"
    output += "29=6,6\n"
    output += "# 30 is the position of LEVEL label in status screen\n"
    output += "30=6,32\n"
    output += "# 31 is the position of HP label in status screen\n"
    output += "31=6,54\n"
    output += "# 32 is the position of MP label in status screen\n"
    output += "32=6,76\n"
    output += "# 33 .. 37 are the positions of words 51 ... 55 in equipping screen\n"
    output += "33=6,98\n"
    output += "34=6,118\n"
    output += "35=6,138\n"
    output += "36=6,158\n"
    output += "37=6,178\n"
    output += "# 38 is the position of current EXP in status screen\n"
    output += "38=58,6\n"
    output += "# 39 is the position of required EXP to level up in status screen\n"
    output += "39=58,15\n"
    output += "# 40 is the position of slash between EXPs in status screen, if set to (0,0), then do not show the slash\n"
    output += "40=0,0\n"
    output += "# 41 is the position of LEVEL in status screen\n"
    output += "41=54,35\n"
    output += "# 42 is the position of current HP in status screen\n"
    output += "42=42,56\n"
    output += "# 43 is the position of max HP in status screen\n"
    output += "43=63,61\n"
    output += "# 44 is the position of slash between cur & max HPs in status screen, if set to (0,0), then do not show the slash\n"
    output += "44=65,58\n"
    output += "# 45 is the position of current MP in status screen\n"
    output += "45=42,78\n"
    output += "# 46 is the position of max MP in status screen\n"
    output += "46=63,83\n"
    output += "# 47 is the position of slash between cur & max MPs in status screen, if set to (0,0), then do not show the slash\n"
    output += "47=65,80\n"
    output += "# 48 .. 52 are the positions of status values in status screen\n"
    output += "48=42,102\n"
    output += "49=42,122\n"
    output += "50=42,142\n"
    output += "51=42,162\n"
    output += "52=42,182\n"
    output += "# 53 .. 58 are the positions of image boxes for equipped equipments in status screen\n"
    output += "53=189,-1\n"
    output += "54=247,39\n"
    output += "55=251,101\n"
    output += "56=201,133\n"
    output += "57=141,141\n"
    output += "58=81,125\n"
    output += "# 59 .. 64 are the positions of names for equipped equipments in status screen\n"
    output += "59=195,38\n"
    output += "60=253,78\n"
    output += "61=257,140\n"
    output += "62=207,172\n"
    output += "63=147,180\n"
    output += "64=87,164\n"
    output += "# 65 .. 80 are the positions of poison names in status screen, note that currently there are no more than 8 poisons can be simulatenously displayed\n"
    output += "65=185,58\n"
    output += "66=185,76\n"
    output += "67=185,94\n"
    output += "68=185,112\n"
    output += "69=185,130\n"
    output += "70=185,148\n"
    output += "71=185,166\n"
    output += "72=185,184\n"
    output += "73=185,184\n"
    output += "74=185,184\n"
    output += "75=185,184\n"
    output += "76=185,184\n"
    output += "77=185,184\n"
    output += "78=185,184\n"
    output += "79=185,184\n"
    output += "80=185,184\n"
    output += "# 81 .. 82 are extra description lines in the item (81) & magic (82) menu, where the first value specifies the lines and the second value should be zero.\n"
    output += "81=2,0\n"
    output += "82=1,0\n"
    output += "# 83 .. 87 customize the layout of MP information and description message in the magic menu.\n"
    output += "# 83 customizes the width of the MP column with its first value. The default value is 5. Use 3 for a narrower one. The second value should be zero.\n"
    output += "83=3,0\n"
    output += "# 84 .. 86 are the coordinates of the slash mark, required MP and current player MP.\n"
    output += "84=30,14\n"
    output += "85=5,14\n"
    output += "86=31,14\n"
    output += "# 87 customizes the X coordinate of the description message with its first value and the second value should be zero.\n"
    output += "87=70,0\n"
    output += "[END LAYOUT]\n\n"

    output += "# This section contains the settings.\n"
    output += "[BEGIN SETTING]\n"
    output += "# Use ISOFont for Europe languages. \n"
    output += "UseISOFont=0\n"
    output += "# A specific font for Simplified Chinese('SimpChin'), Traditional Chinese('TradChin') or Japanese('Japanese'). \n"
    output += "FontFlavor=Japanese\n"
    output += "[END SETTING]\n\n"

    output += "# This section contains the words used by the game.\n"
    output += "[BEGIN WORDS]\n"
    output += "# Each line is a pattern of 'key=value', where key is an integer and value is a string.\n"
    for i in range(0, len(jword_bytes) // options.wordwidth):
        temp = bytearray(data_bytes[i * 10: (i + 1) * 10]).rstrip(b'\x20\x00').decode(options.pcencoding)
        jtemp = bytearray(jword_bytes[i * 16: (i + 1) * 16]).rstrip(b'\x20\x00').decode(options.encoding)
        if options.comment: output += "# Original word: %d=%s\n" % (i, temp)
        output += "%d=%s\n" % (i, jtemp)
    
    def u(s):
        return s.decode('utf-8') if hasattr(s, 'decode') else s

    # 使用 u() 安全拼接带有中文字符的字符串

    output += u("# 600 .. 605 are extra description lines in the equipments menu: Headgear, Body Gear, Clothing, Weapon, Footwear, Accessory.\n")
    output += u("600=頭\n")
    output += u("601=肩\n")
    output += u("602=体\n")
    output += u("603=手\n")
    output += u("604=足\n")
    output += u("605=飾品\n")
    output += u("# The following six words are for ATB only: Battle Speed, 1, 2, 3, 4, 5. They are not used in classical mode.\n")
    output += u("606=戰鬥速度\n")
    output += u("# The following five words are for ATB battle speed. It is not used in classical mode.\n")
    output += u("607=1\n")
    output += u("608=2\n")
    output += u("609=3\n")
    output += u("610=4\n")
    output += u("611=5\n")
    output += u("# The following word is used to ask user whether to launch setting interface on next game start.\n")
    output += u("612=設定に戻る\n")
    output += u("[END WORDS]\n\n")

    output += u("# The following sections contain dialog/description texts used by the game.\n\n")

    print ("Now Processing the MESSAGE Sections. Please wait...")
    
    for s in range(0,26+5+1):
	  #27 sections.
      if s == 0:
        begin_win_group = 0
        end_win_group = 951
        win_script_num = 0
        jpn_script_num = 0
      elif s == 1:
        begin_win_group = 952
        end_win_group = 956
        win_script_num = 7685
        jpn_script_num = 8253
      elif s == 2:
        begin_win_group = 957
        end_win_group = 962
        win_script_num = 7705
        jpn_script_num = 8621
      elif s == 3:
        begin_win_group = 963
        end_win_group = 963
        win_script_num = 7737
        jpn_script_num = 8657
      elif s == 4:
        begin_win_group = 964
        end_win_group = 1000
        win_script_num = 7747
        jpn_script_num = 8667
      elif s == 5:
        begin_win_group = 1001
        end_win_group = 1005
        win_script_num = 8128
        jpn_script_num = 8253
      elif s == 6:
        begin_win_group = 1006
        end_win_group = 2991
        win_script_num = 8217
        jpn_script_num = 8890
      elif s == 7:
        begin_win_group = 2992
        end_win_group = 3158
        win_script_num = 26606
        jpn_script_num = 28904
      elif s == 8:
        begin_win_group = 3159
        end_win_group = 3169
        win_script_num = 27943
        jpn_script_num = 30493
      elif s == 9:
        begin_win_group = 3170
        end_win_group = 3182
        win_script_num = 28027
        jpn_script_num = 35511
      elif s == 10:
        begin_win_group = 3183
        end_win_group = 3203
        win_script_num = 28108
        jpn_script_num = 30587
      elif s == 11:
        begin_win_group = 3204
        end_win_group = 3229
        win_script_num = 28264
        jpn_script_num = 35649
      elif s == 12:
        begin_win_group = 3230
        end_win_group = 3237
        win_script_num = 28488
        jpn_script_num = 36000
      elif s == 13:
        begin_win_group = 3238
        end_win_group = 3247
        win_script_num = 28552
        jpn_script_num = 28817
      elif s == 14:
        begin_win_group = 3248
        end_win_group = 3248
        win_script_num = 28615
        jpn_script_num = 36065
      elif s == 15:
        begin_win_group = 3249
        end_win_group = 3249
        win_script_num = 28620
        jpn_script_num = 35875
      elif s == 16:
        begin_win_group = 3250
        end_win_group = 3258
        win_script_num = 28631
        jpn_script_num = 30435
      elif s == 17:
        begin_win_group = 3259
        end_win_group = 3270
        win_script_num = 28724
        jpn_script_num = 30736
      elif s == 18:
        begin_win_group = 3271
        end_win_group = 3470
        win_script_num = 29048
        jpn_script_num = 31076
      elif s == 19:
        begin_win_group = 3471
        end_win_group = 3483
        win_script_num = 30458
        jpn_script_num = 35421
      elif s == 20:
        begin_win_group = 3484
        end_win_group = 3503
        win_script_num = 30537
        jpn_script_num = 32587
      elif s == 21:
        begin_win_group = 3504
        end_win_group = 3558
        win_script_num = 30654
        jpn_script_num = 36100
      elif s == 22:
        begin_win_group = 3559
        end_win_group = 3576
        win_script_num = 32319
        jpn_script_num = 37786
      elif s == 23:
        begin_win_group = 3577
        end_win_group = 3832
        win_script_num = 32465
        jpn_script_num = 32724
      elif s == 24:
        begin_win_group = 3833
        end_win_group = 3875
        win_script_num = 35220
        jpn_script_num = 38131
      elif s == 25:
        begin_win_group = 3876
        end_win_group = 4203
        win_script_num = 35648
        jpn_script_num = 38540
      elif s == 26:
        begin_win_group = 4204
        end_win_group = 4648
        win_script_num = 39837
        jpn_script_num = 42758
      elif s == 27:
        begin_win_group = 4646
        end_win_group = 4646
        win_script_num = 43514
        jpn_script_num = 16264
      elif s == 28:
        begin_win_group = 4647
        end_win_group = 4647
        win_script_num = 43524
        jpn_script_num = 16264
      elif s == 29:
        begin_win_group = 4648
        end_win_group = 4648
        win_script_num = 43542
        jpn_script_num = 15813
      elif s == 30:
        begin_win_group = 4649
        end_win_group = 4649
        win_script_num = 43544
        jpn_script_num = 15815
      elif s == 31:
        begin_win_group = 4650
        end_win_group = 4650
        win_script_num = 43549
        jpn_script_num = 15821
      #print "One Section..."


      for i in range(begin_win_group,end_win_group+1):
        #print "One group..."
        win_while_should_run=True
        jpn_while_should_run=True
        #还原为True。
        message=""
        jmessage=""
        while win_while_should_run:
        #for i in range(0, len(script_bytes) // 8):
          #print "One Script..."
          op, w1, w2, w3 = struct.unpack('<HHHH', script_bytes[win_script_num * 8 : (win_script_num + 1) * 8])
          if op == 0xFFFF:
            if is_msg_group == 0:
                is_msg_group = 1
                message = "%s %d\n" % ('[BEGIN MESSAGE]', w1)
                if options.comment: comment = "# Original message: %d\n" % w1
            last_index = w1
            msg_count += 1
            msg_begin, msg_end = struct.unpack("<II",index_bytes[w1 * 4 : (w1 + 2) * 4])
            temp = "%s\n" % (msg_bytes[msg_begin : msg_end].decode(options.pcencoding, 'replace'))
            if options.comment: comment += "# " + temp
            
            while jpn_while_should_run:
                jop, jw1, jw2, jw3 = struct.unpack('>HHHH', jscript_bytes[jpn_script_num * 8 : (jpn_script_num + 1) * 8])
                if jop == 0xFFFF:
                    if jis_msg_group == 0:
                        jis_msg_group = 1
                        #temp = ""

                    msg_count += 1
                    jmsg_begin, jmsg_end = struct.unpack("<II",jindex_bytes[jw1 * 4 : (jw1 + 2) * 4])

                    jtemp = "%s\n" % (jmsg_bytes[jmsg_begin : jmsg_end].decode(options.encoding, 'replace'))
                    jmessage += jtemp
                    #print temp
                elif jop == 0x08E:

                    if jis_msg_group == 1:
                        jtemp = "%s\n" % ('[CLEAR MESSAGE]')
                        jmessage += jtemp

                else:
                    if jis_msg_group == 1:
                        jis_msg_group = 0
                        #output += jmessage
                        jpn_while_should_run = False
                    if jpn_script_num == 8660:
                        jis_msg_group = 1
                        jtemp = "%s\n" % ('[CLEAR MESSAGE]')
                        jmessage += jtemp
                        jpn_while_should_run = True
                        jpn_script_num += 1
					#处理一个特殊的对应。Win95版963组对应SS日版958~959两组。
                    #那么，在处理到SS日版第8659+1条脚本的时候，不结束本MESSAGE组，而是插入[CLEAR MESSAGE]。
                    #然后再快进以下，使下一次while循环处理第8662条脚本，即959组的第一条FFFF。

                jpn_script_num += 1


          elif op == 0x008E:

            if is_msg_group == 1:
                temp = "%s\n" % ('[CLEAR MESSAGE]')
                #message += temp
                if options.comment: comment += "# " + temp

          else:
            if is_msg_group == 1:
                is_msg_group = 0
                temp = "%s %d\n\n" % ('[END MESSAGE]', last_index)


                output += comment
                output += message
                output += jmessage
                output += temp
                win_while_should_run = False
          win_script_num += 1
    try:
        import io
        with io.open(options.outputfile, "w", encoding="utf-8", errors="ignore") as f:
            # 兼容处理 Python 2 的 bytes 和 Python 3 的 str
            if hasattr(output, 'decode'):
                f.write(output.decode('utf-8'))
            else:
                f.write(output)
    except:
        traceback.print_exc()
        print ("Error!")
        sys.exit(1)



    print ("OK!")
    print ("Original Dialog script count: " + str(msg_count))

if __name__ == '__main__':
    main()
