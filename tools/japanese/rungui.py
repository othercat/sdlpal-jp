# -*- coding: utf-8 -*-

import tkinter as tk
from tkinter import filedialog, messagebox
import subprocess
import sys
import os
import shutil


# ==========================
# License
# ==========================

LICENSE_TEXT = """
SDLPal Message Generator

Copyright (C) SDLPal Community contributors

This program is free software:
you can redistribute it and/or modify it under the terms of
the GNU General Public License as published by the Free Software Foundation.

The licensing terms of this project may be reviewed and updated
by the SDLPal Community according to the project's contribution rules.

----------------------------------------

"""


# ==========================
# Interface strings
# ==========================

LANG = {

    "title":
        "SDLPal Message Generator / SDLPal メッセージ生成ツール",

    "pc_resource":
        "PC Resource:\nPCリソース:",

    "saturn_resource":
        "Saturn Resource:\nサターンリソース:",

    "output_file":
        "Output SLF:\n出力SLF:",

    "pc_version":
        "PC Version:\nPCバージョン:",

    "simplified":
        "Simplified Chinese (GBK)  \n簡体字中国語 (GBK) ",

    "traditional":
        "Traditional Chinese (BIG5)\n繁体字中国語 (BIG5)",

    "browse":
        "Browse\n参照",

    "generate":
        "Generate\n生成",

    "select_pc":
        "Select PC resource directory",

    "select_saturn":
        "Select Saturn resource directory",

    "save_slf":
        "Save SLF file",

}


# ==========================
# Main window
# ==========================

root = tk.Tk()

root.title(
    LANG["title"]
)

root.geometry(
    "800x620"
)


pc_path = tk.StringVar()
saturn_path = tk.StringVar()
output_path = tk.StringVar()

# Default: Simplified Chinese
pc_encoding = tk.StringVar(
    value="gbk"
)



# ==========================
# Output
# ==========================

def write_output(text):

    output_text.insert(
        tk.END,
        text
    )

    output_text.see(
        tk.END
    )

    root.update()



def show_license():

    output_text.insert(
        tk.END,
        LICENSE_TEXT
    )



# ==========================
# File helper
# ==========================

def find_file(path, filename):

    filename = filename.lower()

    for f in os.listdir(path):

        if f.lower() == filename:

            return os.path.join(
                path,
                f
            )

    return None



# ==========================
# Prepare Steam resources
# ==========================

def prepare_resources(path, encoding):

    logs = []

    logs.append(
        "PC Encoding: "
        + encoding.upper()
        + "\n\n"
    )


    if encoding == "gbk":

        m_source = "M_chs.msg"
        word_source = "Word_chs.dat"

    else:

        m_source = "M_cht.msg"
        word_source = "Word_cht.dat"



    m_target = os.path.join(
        path,
        "M.MSG"
    )


    if not os.path.exists(m_target):

        source = find_file(
            path,
            m_source
        )

        if source:

            shutil.copyfile(
                source,
                m_target
            )

            logs.append(
                "Created M.MSG from:\n"
                + source
                + "\n"
            )
        else:

            try:

                process = subprocess.Popen(

                    [
                        sys.executable,

                        "steam_to_legacy.py",

                        "msg",

                        path,

                        os.path.join(path, m_source),

                        encoding
                    ],

                    stdout=subprocess.PIPE,

                    stderr=subprocess.STDOUT,

                    text=True

                )


                for line in process.stdout:

                    write_output(
                    line
                    )


                process.wait()


                if process.returncode == 0:

                    write_output(
                        "\nSteam_to_legacy msg finished successfully.\n"
                    )


                    shutil.copyfile(
                        m_source,
                        m_target
                    )

                    logs.append(
                        "Created legacy M.MSG from:\n"
                        + m_source
                        + "\n"
                    )



                else:

                    write_output(
                        "\nSteam_to_legacy msg generator failed.\n"
                    )



            except Exception as e:

                write_output(
                    "\nError:\n"
                    + str(e)
                    + "\n"
                )


    else:

        logs.append(
            "Found M.MSG\n"
        )



    word_target = os.path.join(
        path,
        "WORD.DAT"
    )


    if not os.path.exists(word_target):

        source = find_file(
            path,
            word_source
        )

        if source:

            shutil.copyfile(
                source,
                word_target
            )

            logs.append(
                "Created WORD.DAT from:\n"
                + source
                + "\n"
            )

        else:

            try:

                process = subprocess.Popen(

                    [
                        sys.executable,

                        "steam_to_legacy.py",

                        "word",

                        path,

                        os.path.join(path, word_source),

                        encoding
                    ],

                    stdout=subprocess.PIPE,

                    stderr=subprocess.STDOUT,

                    text=True

                )


                for line in process.stdout:

                    write_output(
                    line
                    )


                process.wait()


                if process.returncode == 0:

                    write_output(
                        "\nSteam_to_legacy word finished successfully.\n"
                    )


                    shutil.copyfile(
                        word_source,
                        word_target
                    )

                    logs.append(
                        "Created legacy WORD.DAT from:\n"
                        + word_source
                        + "\n"
                    )



                else:

                    write_output(
                        "\nSteam_to_legacy word generator failed.\n"
                    )



            except Exception as e:

                write_output(
                    "\nError:\n"
                    + str(e)
                    + "\n"
                )

    else:

        logs.append(
            "Found WORD.DAT\n"
        )


    return logs

# ==========================
# File dialogs
# ==========================

def choose_pc():

    path = filedialog.askdirectory(
        title=LANG["select_pc"]
    )

    if path:

        pc_path.set(path)



def choose_saturn():

    path = filedialog.askdirectory(
        title=LANG["select_saturn"]
    )

    if path:

        saturn_path.set(path)



def choose_output():

    path = filedialog.asksaveasfilename(

        title=LANG["save_slf"],

        defaultextension=".slf",

        filetypes=[
            (
                "SDLPal Language File",
                "*.slf"
            ),

            (
                "All Files",
                "*.*"
            )
        ]
    )

    if path:

        output_path.set(path)



# ==========================
# Run generator
# ==========================

def generate():

    if not pc_path.get():

        messagebox.showerror(
            "Error",
            "Please select PC resource directory."
        )

        return


    if not saturn_path.get():

        messagebox.showerror(
            "Error",
            "Please select Saturn resource directory."
        )

        return


    if not output_path.get():

        messagebox.showerror(
            "Error",
            "Please select output file."
        )

        return



    output_text.delete(
        "1.0",
        tk.END
    )


    show_license()


    write_output(
        "Checking resources...\n\n"
    )


    try:

        logs = prepare_resources(
            pc_path.get(),
            pc_encoding.get()
        )


        for line in logs:

            write_output(
                line
            )


    except Exception as e:

        write_output(
            "\nResource preparation failed:\n"
            + str(e)
            + "\n"
        )

        return



    write_output(
        "\nStarting generator...\n\n"
    )


    try:

        process = subprocess.Popen(

            [
                sys.executable,

                "makemessage_j.py",

                pc_path.get(),

                saturn_path.get(),

                output_path.get(),

                pc_encoding.get()
            ],

            stdout=subprocess.PIPE,

            stderr=subprocess.STDOUT,

            text=True

        )


        for line in process.stdout:

            write_output(
                line
            )


        process.wait()


        if process.returncode == 0:

            write_output(
                "\nFinished successfully.\n"
            )

        else:

            write_output(
                "\nGenerator failed.\n"
            )


    except Exception as e:

        write_output(
            "\nError:\n"
            + str(e)
            + "\n"
        )



# ==========================
# GUI Layout
# ==========================


tk.Label(
    root,
    text=LANG["pc_resource"]
).grid(
    row=0,
    column=0,
    sticky="w",
    padx=5,
    pady=5
)


tk.Entry(
    root,
    textvariable=pc_path,
    width=65
).grid(
    row=0,
    column=1
)


tk.Button(
    root,
    text=LANG["browse"],
    command=choose_pc
).grid(
    row=0,
    column=2
)



tk.Label(
    root,
    text=LANG["saturn_resource"]
).grid(
    row=1,
    column=0,
    sticky="w",
    padx=5,
    pady=5
)


tk.Entry(
    root,
    textvariable=saturn_path,
    width=65
).grid(
    row=1,
    column=1
)


tk.Button(
    root,
    text=LANG["browse"],
    command=choose_saturn
).grid(
    row=1,
    column=2
)



tk.Label(
    root,
    text=LANG["output_file"]
).grid(
    row=2,
    column=0,
    sticky="w",
    padx=5,
    pady=5
)


tk.Entry(
    root,
    textvariable=output_path,
    width=65
).grid(
    row=2,
    column=1
)


tk.Button(
    root,
    text=LANG["browse"],
    command=choose_output
).grid(
    row=2,
    column=2
)



tk.Label(
    root,
    text=LANG["pc_version"]
).grid(
    row=3,
    column=0,
    sticky="w",
    padx=5,
    pady=5
)



tk.Radiobutton(
    root,
    text=LANG["simplified"],
    variable=pc_encoding,
    value="gbk"
).grid(
    row=3,
    column=1,
    sticky="w"
)



tk.Radiobutton(
    root,
    text=LANG["traditional"],
    variable=pc_encoding,
    value="big5"
).grid(
    row=4,
    column=1,
    sticky="w"
)



tk.Button(
    root,
    text=LANG["generate"],
    command=generate,
    width=15
).grid(
    row=5,
    column=1,
    pady=10
)



output_text = tk.Text(
    root,
    width=95,
    height=18
)


output_text.grid(
    row=6,
    column=0,
    columnspan=3,
    padx=5,
    pady=5
)



# Show license immediately
show_license()


root.mainloop()