import customtkinter as ctk
from tkinter import filedialog
from CTkMessagebox import CTkMessagebox as msg
import re,os
from intelhex import IntelHex
from mc6809 import CPU
from ins6809 import disassemble_one, format_line

class BitRegisterWidget(ctk.CTkFrame):
    def __init__(self, master, labels=None, command=None, **kwargs):
        super().__init__(master, **kwargs)

        # Uložení odkazu na vaši funkci, která se má spustit při změně
        self.on_change_callback = command

        if labels is None:
            self.labels = ["7", "6", "5", "4", "3", "2", "1", "0"]
        else:
            self.labels = labels

        self.bits = [0] * 8
        self.bit_buttons = []

        self.buttons_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.buttons_frame.pack()

        for i in range(8):
            btn = ctk.CTkButton(
                self.buttons_frame,
                text=self.labels[i],
                width=24,
                font=("monospace", 14),
                command=lambda idx=i: self.toggle_bit(idx)
            )
            btn.grid(row=0, column=i,padx=1)
            self.bit_buttons.append(btn)
            self._update_button_visual(i)

    def toggle_bit(self, index):
        # 1. Změna stavu bitu
        self.bits[index] = 1 - self.bits[index]
        self._update_button_visual(index)

        # 2. Pokud byla definována funkce při změně, zavoláme ji
        if self.on_change_callback is not None:
            # Předáme jí aktuální celkovou hodnotu a index bitu, který se změnil
            self.on_change_callback(self.get_value(), index)

    def _update_button_visual(self, index):
        if self.bits[index] == 1:
            self.bit_buttons[index].configure(fg_color="#33338d")
        else:
            self.bit_buttons[index].configure(fg_color="#bbbbbb")

    def get_value(self):
        binary_str = "".join(str(b) for b in self.bits)
        return int(binary_str, 2)

    def set_value(self, value):
        if not (0 <= value <= 255):
            raise ValueError("Hodnota musí být v rozmezí 0 až 255")
        binary_str = f"{value:08b}"
        for i in range(8):
            self.bits[i] = int(binary_str[i])
            self._update_button_visual(i)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.geometry("500x400")
        self.title("mc6809")
        self.resizable(width=False, height=False)

        self.mem = bytearray(65536)
        self.cpu = CPU(self.Read, self.Write, variant="6309",illegal_policy="trap")

        fr = ctk.CTkFrame(self, fg_color="transparent")
        fr.pack(padx=1, pady=1)

        # Registrace validační funkce v systému Tkinter
        vcmd2 = (self.register(self.validate_hex_2), '%P')
        vcmd4 = (self.register(self.validate_hex_4), '%P')

        # add widgets to app
        labels = ["A","B","E","F","X","Y","U","S","V","PC","DP"]
        self.regs = []
        for i in range(4):
            var = ctk.StringVar(value="00")
            self.regs.append(var)
            label = ctk.CTkLabel(fr,
                width=45,
                justify='center',
                text=labels[i]
            )
            label.grid(row=0, column=i)
            entry = ctk.CTkEntry(fr,
                width=45,
                textvariable=self.regs[i],
                justify='center',
                font=("monospace", 14),
                validate="key",          # Validace se spustí při stisku klávesy
                validatecommand=vcmd2    # Odkaz na registrovanou funkci
            )
            entry.grid(row=1, column=i)
            # Lambda funkce nám umožní předat index 'i' a aktuální text z widgetu
            entry.bind("<Return>", lambda event, idx=i: self.uloz_hodnotu(idx, event.widget.get()))
            entry.bind("<FocusOut>", lambda event, idx=i: self.uloz_hodnotu(idx, event.widget.get()))
        label = ctk.CTkLabel(fr,
            width=45,
            justify='center',
            text="D"
        )
        label.grid(row=2, column=0, columnspan=2)
        label = ctk.CTkLabel(fr,
            width=45,
            justify='center',
            text="W"
        )
        label.grid(row=2, column=2, columnspan=2)
        label = ctk.CTkLabel(fr,
            width=45,
            justify='center',
            text="Q",
        )
        label.grid(row=2, column=1, columnspan=2)
        r = 3
        for i in range(4, 10):
            var = ctk.StringVar(value="0000")
            self.regs.append(var)
            label = ctk.CTkLabel(fr,
                width=16,
                justify='center',
                text=labels[i]
            )
            label.grid(row=r, column=4)
            entry = ctk.CTkEntry(fr,
                width=90,
                textvariable=self.regs[i],
                justify='center',
                font=("monospace", 14),
                validate="key",          # Validace se spustí při stisku klávesy
                validatecommand=vcmd4    # Odkaz na registrovanou funkci
            )
            entry.grid(row=r, column=5)
            # Lambda funkce nám umožní předat index 'i' a aktuální text z widgetu
            entry.bind("<Return>", lambda event, idx=i: self.uloz_hodnotu(idx, event.widget.get()))
            entry.bind("<FocusOut>", lambda event, idx=i: self.uloz_hodnotu(idx, event.widget.get()))
            r += 1
        i = 10
        var = ctk.StringVar(value="00")
        self.regs.append(var)
        label = ctk.CTkLabel(fr,
            width=16,
            justify='center',
            text=labels[i]
        )
        label.grid(row=r, column=4)
        entry = ctk.CTkEntry(fr,
            width=45,
            textvariable=self.regs[i],
            justify='center',
            font=("monospace", 14),
            validate="key",          # Validace se spustí při stisku klávesy
            validatecommand=vcmd2    # Odkaz na registrovanou funkci
        )
        entry.grid(row=r, column=5)
        # Lambda funkce nám umožní předat index 'i' a aktuální text z widgetu
        entry.bind("<Return>", lambda event, idx=i: self.uloz_hodnotu(idx, event.widget.get()))
        entry.bind("<FocusOut>", lambda event, idx=i: self.uloz_hodnotu(idx, event.widget.get()))
        r += 1
        label = ctk.CTkLabel(fr,
            width=16,
            justify='center',
            text="CC"
        )
        label.grid(row=r, column=4)
        self.cc = BitRegisterWidget(
            master=fr,
            labels=["E","F","H","I","N","Z","V","C"],
            command=self.zmena_cc
        )
        self.cc.grid(row=r, column=5)
        r += 1
        label = ctk.CTkLabel(fr,
            width=16,
            justify='center',
            text="MD"
        )
        label.grid(row=r, column=4)
        self.md = BitRegisterWidget(
            master=fr,
            labels=["0","I","-","-","-","-","F","N"],
            command=self.zmena_md
        )
        self.md.grid(row=r, column=5)
        self.ins = ctk.CTkTextbox(
            master=fr,
            width=200,
            corner_radius=0,
            font=("monospace", 14)
        )
        self.ins.grid(row=3, column=0, rowspan=7, columnspan=4)

        LoadBtn = ctk.CTkButton(fr, width=50, text="Load", command=self.Load_event)
        LoadBtn.grid(row=10, column=0)
        SaveBtn = ctk.CTkButton(fr, width=50, text="Save", command=self.Save_event)
        SaveBtn.grid(row=10, column=1)
        ResetBtn = ctk.CTkButton(fr, width=50, text="Reset", command=self.Reset_event)
        ResetBtn.grid(row=10, column=2)
        StepBtn = ctk.CTkButton(fr, width=50, text="Step", command=self.Step_event)
        StepBtn.grid(row=10, column=3)

    # add methods to app
    def Read(self, addr:int) -> int:
        return self.mem[addr]

    def Write(self, addr:int, data:int) -> None:
        self.mem[addr] = data

    def validate_hex_2(self, P):
        if P == "" or (re.fullmatch(r"[0-9a-fA-F]*", P) and len(P) <= 2):
            return True
        return False

    def validate_hex_4(self, P):
        if P == "" or (re.fullmatch(r"[0-9a-fA-F]*", P) and len(P) <= 4):
            return True
        return False

    def uloz_hodnotu(self, index, aktualni_text):
        # "A","B","E","F","X","Y","U","S","V","PC","DP"
        if index == 0:
            self.cpu.r.a = int(aktualni_text, 16)
        elif index == 1:
            self.cpu.r.b = int(aktualni_text, 16)
        elif index == 2:
            self.cpu.r.e = int(aktualni_text, 16)
        elif index == 3:
            self.cpu.r.f = int(aktualni_text, 16)
        elif index == 4:
            self.cpu.r.x = int(aktualni_text, 16)
        elif index == 5:
            self.cpu.r.y = int(aktualni_text, 16)
        elif index == 6:
            self.cpu.r.u = int(aktualni_text, 16)
        elif index == 7:
            self.cpu.r.s = int(aktualni_text, 16)
        elif index == 8:
            self.cpu.r.v = int(aktualni_text, 16)
        elif index == 9:
            self.cpu.r.pc = int(aktualni_text, 16)
            self.update()
        elif index == 10:
            self.cpu.r.dp = int(aktualni_text, 16)

    def zmena_cc(self, hodnota, index):
        self.cpu.r.cc = int(hodnota, 16)

    def zmena_md(self, hodnota, index):
        self.cpu.r.md = int(hodnota, 16)

    def update(self):
        # "A","B","E","F","X","Y","U","S","V","PC","DP"
        self.regs[0].set(f"{self.cpu.r.a:02X}")
        self.regs[1].set(f"{self.cpu.r.b:02X}")
        self.regs[2].set(f"{self.cpu.r.e:02X}")
        self.regs[3].set(f"{self.cpu.r.f:02X}")
        self.regs[4].set(f"{self.cpu.r.x:04X}")
        self.regs[5].set(f"{self.cpu.r.y:04X}")
        self.regs[6].set(f"{self.cpu.r.u:04X}")
        self.regs[7].set(f"{self.cpu.r.s:04X}")
        self.regs[8].set(f"{self.cpu.r.v:04X}")
        self.regs[9].set(f"{self.cpu.r.pc:04X}")
        self.regs[10].set(f"{self.cpu.r.dp:02X}")
        self.cc.set_value(self.cpu.r.cc)
        self.md.set_value(self.cpu.r.md)
        self.ins.delete("0.0", "end")
        pc = self.cpu.r.pc
        for i in range(10):
            d = disassemble_one(self.Read, pc, True)
            self.ins.insert("end",f"{d[0]:04X} {d[2]} {d[3]}\n")
            pc = d[4]

    def Load_event(self):
        filetypes = (
            ('Binary files', '*.bin'),
            ('Intel HEX files', '*.hex')
        )
        path = filedialog.askopenfilename(
            title="Select a File",
            filetypes=filetypes
        )
        if path == None:
            return
        if path.endswith(".bin"):
            if os.stat(path).st_size != 65536:
                msg(
                    title="Error",
                    message="Binary files of 65536 supported",
                    icon="cancel" # Možnosti: "cancel" (křížek), "warning", "info"
                )
                return
            else:
                f = open(path, "rb")
                self.mem = f.read(65536)
                f.close()
                self.Reset_event()
                return
        if path.endswith(".hex"):
            ih = IntelHex(path)
            self.mem = bytearray(ih.tobinarray(start=0,end=65536))
            self.Reset_event()
            return

    def Save_event(self):
        print("Save event")

    def Reset_event(self):
        self.cpu.reset()
        self.update()

    def Step_event(self):
        self.cpu.step()
        self.update()


app = App()
app.mainloop()
