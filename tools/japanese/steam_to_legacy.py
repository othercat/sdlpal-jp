
# -*- coding: utf-8 -*-

from __future__ import print_function

import sys
import os
import struct
import io
import traceback


# Steam private-use characters which represent characters from
# the original legacy resources.
SPECIAL_CHARACTERS = {
    0xE010: b'\xAA\xB1',
    0xE16D: b'\xAD\xF4',
    0xE47E: b'\xFE\xB7',
    0xE4C7: b'\xA1\x41',
    0xE4C9: b'\xA1\x43',
}


WORD_LENGTH = 10


def encode_text(text, encoding):
    data = bytearray()

    for ch in text:
        code = ord(ch)

        if code in SPECIAL_CHARACTERS:
            data.extend(SPECIAL_CHARACTERS[code])
            continue

        try:
            data.extend(ch.encode(encoding))

        except UnicodeEncodeError:

            # Python's standard "big5" codec does not contain
            # every character used by the traditional Chinese
            # Steam resource.
            #
            # CP950 is the Windows Traditional Chinese extension
            # and matches the legacy resource for characters such
            # as U+FF5E:
            #
            #   ～ -> A1 E3
            #
            if encoding == 'big5':
                try:
                    data.extend(ch.encode('cp950'))
                    continue
                except UnicodeEncodeError:
                    pass

            print('')
            print('ERROR: Cannot encode character.')
            print('  Encoding : %s' % encoding)
            print('  Character: U+%04X' % code)
            print('  Text     : %s' % text)
            raise

    return bytes(data)


def read_text_resource(filename):
    records = {}

    with io.open(
        filename,
        'r',
        encoding='utf-16-le'
    ) as f:

        for line_number, line in enumerate(f, 1):

            # Remove only line endings.
            # Spaces are part of the actual resource text.
            line = line.rstrip(u'\r\n')

            if not line:
                continue

            # Official comments.
            if line.startswith(u';'):
                continue

            # Split at the first colon only.
            pos = line.find(u':')

            if pos < 0:
                print(
                    'Warning: line %d has no ":"; skipped.'
                    % line_number
                )
                continue

            id_text = line[:pos]
            text = line[pos + 1:]

            try:
                record_id = int(id_text)
            except ValueError:
                print(
                    'Warning: invalid ID at line %d; skipped.'
                    % line_number
                )
                continue

            # The official format says that a later duplicate ID
            # overwrites the previous entry.
            records[record_id] = text

    return records


def read_sss_index(gamepath):
    filename = os.path.join(gamepath, 'SSS.MKF')

    with open(filename, 'rb') as f:

        f.seek(12, os.SEEK_SET)

        offset_begin, script_begin, file_end = struct.unpack(
            '<III',
            f.read(12)
        )

        f.seek(offset_begin, os.SEEK_SET)

        index_bytes = f.read(
            script_begin - offset_begin
        )

    return index_bytes


def get_message_length(index_bytes, message_id):

    count = len(index_bytes) // 4

    if message_id < 0 or message_id >= count:
        raise ValueError(
            'Message ID %d is outside SSS.MKF index.'
            % message_id
        )

    offset = message_id * 4

    msg_begin = struct.unpack(
        '<I',
        index_bytes[offset:offset + 4]
    )[0]

    if message_id == count - 1:
        msg_end = msg_begin
    else:
        msg_end = struct.unpack(
            '<I',
            index_bytes[offset + 4:offset + 8]
        )[0]

    if msg_end < msg_begin:
        raise ValueError(
            'Invalid SSS.MKF index for message %d: %d -> %d'
            % (
                message_id,
                msg_begin,
                msg_end
            )
        )

    return msg_begin, msg_end


def convert_msg(gamepath, output_path, encoding):

    if encoding == 'gbk':
        source_name = 'MSG_chs.txt'
    else:
        source_name = 'MSG_cht.txt'

    source_path = os.path.join(
        gamepath,
        source_name
    )

    print('==================================================')
    print('Converting MSG')
    print('==================================================')
    print('Source   : %s' % source_name)
    print('Encoding : %s' % encoding)
    print('Output   : %s' % output_path)
    print('')

    index_bytes = read_sss_index(gamepath)

    messages = read_text_resource(source_path)

    index_count = len(index_bytes) // 4

    print(
        'MSG records      : %d'
        % len(messages)
    )

    print(
        'SSS.MKF index    : %d'
        % index_count
    )

    print('')

    output = bytearray()

    errors = 0
    padded = 0

    for message_id in sorted(messages.keys()):

        if message_id < 0 or message_id >= index_count:
            print(
                'ERROR: Message ID %d is outside '
                'SSS.MKF index.'
                % message_id
            )
            errors += 1
            continue

        text = messages[message_id]

        msg_begin, msg_end = get_message_length(
            index_bytes,
            message_id
        )

        expected_length = msg_end - msg_begin

        data = encode_text(
            text,
            encoding
        )

        actual_length = len(data)

        if actual_length > expected_length:

            print('')
            print('ERROR: Message is too long.')
            print('  ID       : %d' % message_id)
            print(
                '  Expected : %d bytes'
                % expected_length
            )
            print(
                '  Actual   : %d bytes'
                % actual_length
            )
            print(
                '  Overflow : %d bytes'
                % (
                    actual_length -
                    expected_length
                )
            )
            print('  Text     : %s' % text)

            errors += 1
            continue

        if actual_length < expected_length:

            padding = (
                expected_length -
                actual_length
            )

            data += b'\x20' * padding

            padded += 1

            print(
                'ID %d: %d -> %d bytes '
                '(padded %d)'
                % (
                    message_id,
                    actual_length,
                    expected_length,
                    padding
                )
            )

        output.extend(data)

    if errors:

        print('')
        print(
            'ERROR: %d message(s) failed.'
            % errors
        )
        print(
            'The MSG output file was NOT created.'
        )

        return False

    with open(output_path, 'wb') as f:
        f.write(bytes(output))

    print('')
    print(
        'Messages padded: %d'
        % padded
    )
    print(
        'Output size    : %d bytes'
        % len(output)
    )
    print('')
    print(
        'M.MSG created successfully.'
    )
    print('')

    return True


def convert_word(gamepath, output_path, encoding):

    if encoding == 'gbk':
        source_name = 'WORD_chs.txt'
    else:
        source_name = 'WORD_cht.txt'

    source_path = os.path.join(
        gamepath,
        source_name
    )

    print('==================================================')
    print('Converting WORD')
    print('==================================================')
    print('Source   : %s' % source_name)
    print('Encoding : %s' % encoding)
    print('Output   : %s' % output_path)
    print('')

    words = read_text_resource(source_path)

    print(
        'WORD records: %d'
        % len(words)
    )

    print('')

    output = bytearray()

    errors = 0
    padded = 0

    for word_id in sorted(words.keys()):

        text = words[word_id]

        data = encode_text(
            text,
            encoding
        )

        actual_length = len(data)

        if actual_length > WORD_LENGTH:

            print('')
            print('ERROR: WORD entry is too long.')
            print(
                '  ID       : %d'
                % word_id
            )
            print(
                '  Expected : %d bytes'
                % WORD_LENGTH
            )
            print(
                '  Actual   : %d bytes'
                % actual_length
            )
            print(
                '  Overflow : %d bytes'
                % (
                    actual_length -
                    WORD_LENGTH
                )
            )
            print(
                '  Word     : %s'
                % text
            )

            errors += 1
            continue

        if actual_length < WORD_LENGTH:

            padding = (
                WORD_LENGTH -
                actual_length
            )

            data += b'\x20' * padding

            padded += 1

            print(
                'ID %d: %d -> %d bytes '
                '(padded %d)'
                % (
                    word_id,
                    actual_length,
                    WORD_LENGTH,
                    padding
                )
            )

        output.extend(data)

    if errors:

        print('')
        print(
            'ERROR: %d WORD entry(s) failed.'
            % errors
        )
        print(
            'The WORD output file was NOT created.'
        )

        return False

    with open(output_path, 'wb') as f:
        f.write(bytes(output))

    print('')
    print(
        'WORD entries padded: %d'
        % padded
    )
    print(
        'Output size        : %d bytes'
        % len(output)
    )
    print('')
    print(
        'WORD.DAT created successfully.'
    )
    print('')

    return True


def main():

    if len(sys.argv) < 4 or len(sys.argv) > 5:

        print('Usage:')
        print('')
        print(
            '  python steam_msg_to_legacy.py '
            'MODE GAME_PATH OUTPUT [gbk|big5]'
        )
        print('')
        print('MODE:')
        print('  msg   Convert MSG_chs/cht.txt -> M.MSG')
        print('  word  Convert WORD_chs/cht.txt -> WORD.DAT')
        print('  all   Convert both resources')
        print('')
        print('Encoding:')
        print('  gbk   -> *_chs.txt')
        print('  big5  -> *_cht.txt')
        print('')
        print(
            'Default encoding: gbk'
        )

        sys.exit(1)

    mode = sys.argv[1].lower()
    gamepath = sys.argv[2]
    output_path = sys.argv[3]

    if len(sys.argv) >= 5:
        encoding = sys.argv[4].lower()
    else:
        encoding = 'gbk'

    if mode not in (
        'msg',
        'word',
        'all'
    ):

        print(
            'MODE must be msg, word or all.'
        )

        sys.exit(1)

    if encoding not in (
        'gbk',
        'big5'
    ):

        print(
            'Encoding must be gbk or big5.'
        )

        sys.exit(1)

    if not os.path.isdir(gamepath):

        print(
            'ERROR: Game path does not exist:'
        )
        print(
            '  %s'
            % gamepath
        )

        sys.exit(1)

    if encoding == 'gbk':

        msg_name = 'MSG_chs.txt'
        word_name = 'WORD_chs.txt'

    else:

        msg_name = 'MSG_cht.txt'
        word_name = 'WORD_cht.txt'

    try:

        if mode == 'msg':

            source = os.path.join(
                gamepath,
                msg_name
            )

            if not os.path.isfile(source):

                print(
                    'ERROR: %s not found.'
                    % msg_name
                )

                sys.exit(1)

            if not os.path.isfile(
                os.path.join(
                    gamepath,
                    'SSS.MKF'
                )
            ):

                print(
                    'ERROR: SSS.MKF not found.'
                )

                sys.exit(1)

            success = convert_msg(
                gamepath,
                output_path,
                encoding
            )

            if not success:
                sys.exit(1)

        elif mode == 'word':

            source = os.path.join(
                gamepath,
                word_name
            )

            if not os.path.isfile(source):

                print(
                    'ERROR: %s not found.'
                    % word_name
                )

                sys.exit(1)

            success = convert_word(
                gamepath,
                output_path,
                encoding
            )

            if not success:
                sys.exit(1)

        else:

            msg_source = os.path.join(
                gamepath,
                msg_name
            )

            word_source = os.path.join(
                gamepath,
                word_name
            )

            if not os.path.isfile(msg_source):

                print(
                    'ERROR: %s not found.'
                    % msg_name
                )

                sys.exit(1)

            if not os.path.isfile(word_source):

                print(
                    'ERROR: %s not found.'
                    % word_name
                )

                sys.exit(1)

            if not os.path.isfile(
                os.path.join(
                    gamepath,
                    'SSS.MKF'
                )
            ):

                print(
                    'ERROR: SSS.MKF not found.'
                )

                sys.exit(1)

            # In "all" mode the output argument is a directory.
            if not os.path.isdir(output_path):

                print(
                    'ERROR: Output path must be '
                    'an existing directory in all mode.'
                )

                sys.exit(1)

            msg_output = os.path.join(
                output_path,
                'M.MSG'
            )

            word_output = os.path.join(
                output_path,
                'WORD.DAT'
            )

            success = convert_msg(
                gamepath,
                msg_output,
                encoding
            )

            if not success:
                sys.exit(1)

            success = convert_word(
                gamepath,
                word_output,
                encoding
            )

            if not success:
                sys.exit(1)

            print(
                'All conversions completed successfully.'
            )

    except Exception:

        print('')
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
