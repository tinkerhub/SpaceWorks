# Item codes and component categories

Every makerspace on a SpaceWorks deployment classifies components the same way, and every
inventory item carries a short code built from three parts:

```
<MAKERSPACE PREFIX>-<CATEGORY CODE>-<LETTER>        e.g. TC-MCU-A
```

The staff console shows the same reference under **Inventory → Categories → Classification
guide**, and the code appears on the public catalogue card, the staff inventory table, the item
editor and the CSV export.

## 1. Component category reference

New makerspaces start with these ten categories. A makerspace can add its own (any 2–4 capital
letters, e.g. `TLS` for hand tools), but should use these for anything they cover.

| Code | Category | What goes here | Examples |
| --- | --- | --- | --- |
| `MCU` | Microcontrollers & Computing Boards | Programmable boards and single-board computers | ESP32, ESP8266, Arduino UNO, Arduino Nano, XIAO RP2040, Raspberry Pi Pico, Raspberry Pi |
| `SNS` | Sensors | Components that measure or detect something | MPU6050, DHT11, DHT22, HC-SR04, PIR, IR sensor, soil moisture sensor, ToF sensor, GPS sensor/module |
| `ACT` | Actuators | Components that create movement or physical output | Servo motors, BO motors, N20 motors, NEMA 17 stepper motors, DC motors |
| `PWR` | Power & Power Management | Components for power conversion, regulation and charging | LM2596 buck converter, XL6009 boost converter, TP4056 charging module, DC-DC converters |
| `NET` | Networking & Communication | Components that provide wireless or wired communication | LoRa modules, GSM/4G modules, Bluetooth modules, RFID communication modules |
| `MOD` | Modules & Accessories | Supporting modules, peripherals and interface boards | Microphone modules, USB hubs, CH340 USB-to-serial modules, general-purpose relay modules |
| `CBL` | Cables & Connectors | Reusable wires, cables and connection accessories | Jumper wires, USB cables, HDMI cables, Dupont connectors, ribbon cables, header pins |
| `CON` | Consumables | Items that are used up, depleted or regularly replaced | Solder wire, heat-shrink tubing, electrical tape, batteries intended for replacement, resistors and LEDs managed as bulk stock |
| `DSP` | Displays | Components used to display visual information | OLED displays, TFT LCDs, 16×2 LCDs, 7-segment displays |
| `DRV` | Motor Drivers & Motion Control | Electronic modules that control motors and motion | DRV8825, DRV8833, L298N, PCA9685 |

## 2. Rules for classifying components

To keep the inventory consistent, follow these rules:

- **One component type = one item code.** Record the available quantity against that code.
- **Use the primary function** to decide the category. Avoid assigning multiple categories to the same item.
- **ESP32-CAM:** classify under `MCU` because it contains a programmable microcontroller.
- **RFID modules:** classify under `NET` when used primarily for communication; use `MOD` for
  general-purpose interface modules. Choose one convention and apply it consistently.
- **Relay modules:** classify under `MOD` for general-purpose switching. Motor-specific driver
  boards belong under `DRV`.
- **Reusable cables and connectors:** keep them under `CBL`, not `CON`.
- **Small electronic parts:** use `CON` when they're managed as bulk consumable stock; use their
  functional category when they're tracked as reusable components.

## 3. Item code format

Example for TinkerSpace Calicut (prefix `TC`):

| Item code | Component |
| --- | --- |
| `TC-MCU-A` | ESP32 DevKit |
| `TC-MCU-B` | Arduino UNO |
| `TC-SNS-A` | MPU6050 sensor |
| `TC-SNS-B` | DHT22 sensor |
| `TC-ACT-A` | Servo motor |
| `TC-PWR-A` | LM2596 buck converter |
| `TC-NET-A` | LoRa module |
| `TC-MOD-A` | Microphone module |
| `TC-CBL-A` | Jumper wires |
| `TC-CON-A` | Solder wire |
| `TC-DSP-A` | OLED display |
| `TC-DRV-A` | L298N motor driver |

### The prefix

- Each makerspace has its own prefix, **unique across the whole platform**, so a code names one
  part in one makerspace wherever it is read.
- The default is the first letter of the first word plus the first letter of the last word:
  "Tinkerspace Kochi" → `TK`, "Tinkerspace Calicut" → `TC`.
- If that prefix is already taken, the first letter stays and the **second letter changes**,
  working through the rest of the name: a later "Tinkerspace Chennai" gets `TH`, then `TE`…
- A Space Manager or superadmin can override it under **Settings → General → Item codes** (1–6
  letters or digits). A prefix another makerspace holds is refused. Clearing the field goes back
  to the default.

### The letter

- Letters are handed out automatically, in order, per category: A … Z, then AA, AB, …
- **Letters are never reused.** Deleting `TC-MCU-B` does not free "B", so an old printed label can
  never end up naming a different part.
- Moving an item to another category gives it the next letter there, because the code describes
  the category.
- Only the parts are stored; the full code is assembled when it is shown. Changing the prefix or
  a category's code therefore relabels every item at once — and frees the old value, which another
  makerspace (or category) may then take. Treat a rename as a relabel: reprint any labels that
  carry the old code.
- Items in a category without a code (or with no category) have no item code yet; the public
  catalogue shows their catalogue number (`#0042`) instead.

### Searching and importing

- Staff inventory search and the public catalogue search both accept a code, with or without the
  prefix (`TC-MCU-A` or `MCU-A`).
- Bulk import's `category` column accepts either the category name or its code (`MCU`).
- The inventory CSV export has an `item_code` column.

## Upgrading an existing deployment

The upgrade migrations (`makerspaces 0072`–`0073`, `inventory 0010`–`0011`) change no names and delete nothing:

1. every makerspace gets a prefix as above, oldest makerspace first;
2. the old default categories get the matching code — Microcontrollers → `MCU`, Sensors → `SNS`,
   Actuators → `ACT`, Cables → `CBL`, Accessories → `MOD` — and a category already named like a
   standard one (e.g. "Displays") gets that code;
3. the missing standard categories are added;
4. every categorised item gets a letter in the order it was created.

The old "SBCs" and "Microprocessors" categories are left without a code. Move their items into
`MCU` (or give the category its own code) and delete the empty category when you are ready.
