/** The platform-wide component categories, mirrored from backend `apps/inventory/categories.py`. */
export type StandardCategory = { code: string; name: string; scope: string; examples: string };

export const STANDARD_CATEGORIES: StandardCategory[] = [
  { code: "MCU", name: "Microcontrollers & Computing Boards", scope: "Programmable boards and single-board computers", examples: "ESP32, ESP8266, Arduino UNO, Arduino Nano, XIAO RP2040, Raspberry Pi Pico, Raspberry Pi" },
  { code: "SNS", name: "Sensors", scope: "Components that measure or detect something", examples: "MPU6050, DHT11, DHT22, HC-SR04, PIR, IR sensor, soil moisture sensor, ToF sensor, GPS sensor/module" },
  { code: "ACT", name: "Actuators", scope: "Components that create movement or physical output", examples: "Servo motors, BO motors, N20 motors, NEMA 17 stepper motors, DC motors" },
  { code: "PWR", name: "Power & Power Management", scope: "Components for power conversion, regulation and charging", examples: "LM2596 buck converter, XL6009 boost converter, TP4056 charging module, DC-DC converters" },
  { code: "NET", name: "Networking & Communication", scope: "Components that provide wireless or wired communication", examples: "LoRa modules, GSM/4G modules, Bluetooth modules, RFID communication modules" },
  { code: "MOD", name: "Modules & Accessories", scope: "Supporting modules, peripherals and interface boards", examples: "Microphone modules, USB hubs, CH340 USB-to-serial modules, general-purpose relay modules" },
  { code: "CBL", name: "Cables & Connectors", scope: "Reusable wires, cables and connection accessories", examples: "Jumper wires, USB cables, HDMI cables, Dupont connectors, ribbon cables, header pins" },
  { code: "CON", name: "Consumables", scope: "Items that are used up, depleted or regularly replaced", examples: "Solder wire, heat-shrink tubing, electrical tape, replacement batteries, resistors and LEDs managed as bulk stock" },
  { code: "DSP", name: "Displays", scope: "Components used to display visual information", examples: "OLED displays, TFT LCDs, 16×2 LCDs, 7-segment displays" },
  { code: "DRV", name: "Motor Drivers & Motion Control", scope: "Electronic modules that control motors and motion", examples: "DRV8825, DRV8833, L298N, PCA9685" },
];

/** The classification rules shown beside the reference table. `code` spans render as chips. */
export const CLASSIFICATION_RULES: { title: string; body: string }[] = [
  { title: "One component type = one item code.", body: "Record the available quantity against that code." },
  { title: "Use the primary function", body: "to decide the category. Avoid assigning multiple categories to the same item." },
  { title: "ESP32-CAM:", body: "classify under `MCU` because it contains a programmable microcontroller." },
  { title: "RFID modules:", body: "classify under `NET` when used primarily for communication; use `MOD` for general-purpose interface modules. Choose one convention and apply it consistently." },
  { title: "Relay modules:", body: "classify under `MOD` for general-purpose switching. Motor-specific driver boards belong under `DRV`." },
  { title: "Reusable cables and connectors:", body: "keep them under `CBL`, not `CON`." },
  { title: "Small electronic parts:", body: "use `CON` when they're managed as bulk consumable stock; use their functional category when they're tracked as reusable components." },
];

/** `TC-MCU-A`: what an item code looks like for this prefix, for previews and helper text. */
export function sampleItemCode(prefix: string | undefined, code = "MCU", letter = "A") {
  return [prefix?.trim().toUpperCase(), code, letter].filter(Boolean).join("-");
}
