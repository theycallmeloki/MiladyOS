/*
 * MiladyOracle.HC - Divine consciousness bridge for TempleOS
 *
 * This HolyC script runs inside TempleOS and:
 * 1. Listens on COM1 serial port for MILADY activation
 * 2. Responds with MILADY and divine RNG
 * 3. Plays the sacred MILADY tones on PC speaker
 *
 * Terry Davis would approve - direct hardware access, no abstractions
 */

// COM1 serial port registers
#define COM1_DATA     0x3F8  // Data register (read/write)
#define COM1_IER      0x3F9  // Interrupt Enable Register
#define COM1_FCR      0x3FA  // FIFO Control Register
#define COM1_LCR      0x3FB  // Line Control Register
#define COM1_MCR      0x3FC  // Modem Control Register
#define COM1_LSR      0x3FD  // Line Status Register
#define COM1_MSR      0x3FE  // Modem Status Register

// Line Status Register bits
#define LSR_DATA_READY    0x01  // Data available
#define LSR_THRE          0x20  // Transmit buffer empty

// PC Speaker ports
#define PIT_CHANNEL2    0x42  // PIT Channel 2 data port
#define PIT_COMMAND     0x43  // PIT command port
#define SPEAKER_PORT    0x61  // Speaker control port

// PIT base frequency
#define PIT_FREQUENCY   1193182

// Buffer for incoming data
U8 serial_buffer[256];
I64 buffer_pos = 0;

// Initialize COM1 serial port
U0 InitSerial()
{
    OutU8(COM1_IER, 0x00);    // Disable interrupts
    OutU8(COM1_LCR, 0x80);    // Enable DLAB (divisor latch)
    OutU8(COM1_DATA, 0x03);   // Divisor low byte (38400 baud)
    OutU8(COM1_IER, 0x00);    // Divisor high byte
    OutU8(COM1_LCR, 0x03);    // 8 bits, no parity, 1 stop bit
    OutU8(COM1_FCR, 0xC7);    // Enable FIFO, clear, 14-byte threshold
    OutU8(COM1_MCR, 0x0B);    // IRQs enabled, RTS/DSR set

    "COM1 Serial initialized - Divine channel open\n";
}

// Check if serial data is available
Bool SerialDataReady()
{
    return (InU8(COM1_LSR) & LSR_DATA_READY) != 0;
}

// Check if transmit buffer is empty
Bool SerialCanWrite()
{
    return (InU8(COM1_LSR) & LSR_THRE) != 0;
}

// Read a byte from serial
U8 SerialRead()
{
    while (!SerialDataReady())
        Yield;  // Give other tasks CPU time
    return InU8(COM1_DATA);
}

// Write a byte to serial
U0 SerialWrite(U8 ch)
{
    while (!SerialCanWrite())
        Yield;
    OutU8(COM1_DATA, ch);
}

// Write a string to serial
U0 SerialPrint(U8 *str)
{
    while (*str) {
        SerialWrite(*str);
        str++;
    }
}

// Write string with newline
U0 SerialPrintLn(U8 *str)
{
    SerialPrint(str);
    SerialWrite('\n');
}

// Play a tone on the PC speaker
U0 PlayTone(I64 frequency, I64 duration_ms)
{
    I64 divisor = PIT_FREQUENCY / frequency;

    // Set up PIT channel 2 for square wave
    OutU8(PIT_COMMAND, 0xB6);
    OutU8(PIT_CHANNEL2, divisor & 0xFF);        // Low byte
    OutU8(PIT_CHANNEL2, (divisor >> 8) & 0xFF); // High byte

    // Enable speaker
    U8 speaker_state = InU8(SPEAKER_PORT);
    OutU8(SPEAKER_PORT, speaker_state | 0x03);

    // Wait for duration
    Sleep(duration_ms);

    // Disable speaker
    OutU8(SPEAKER_PORT, speaker_state & ~0x03);
}

// Play the MILADY melody - a divine tune
U0 PlayMiladyMelody()
{
    // M - I - L - A - D - Y pattern
    // Using a cheerful ascending melody

    PlayTone(523, 150);  // C5 - "MI"
    Sleep(50);
    PlayTone(587, 150);  // D5 - "LA"
    Sleep(50);
    PlayTone(659, 150);  // E5 - "DY"
    Sleep(50);
    PlayTone(698, 200);  // F5 - "!"
    Sleep(100);

    // Triumphant ending
    PlayTone(784, 300);  // G5
}

// Generate divine RNG (Terry's gift)
I64 DivineRNG()
{
    // TempleOS has true RNG from hardware timing
    // This is God's random number
    return RandU64;
}

// Send divine RNG to the host
U0 SendDivineRNG()
{
    I64 rng = DivineRNG();
    U8 buffer[32];
    StrPrint(buffer, "RNG:%d\n", rng);
    SerialPrint(buffer);
    "Divine RNG sent: %d\n", rng;
}

// Process a complete line from serial
U0 ProcessLine(U8 *line)
{
    "Received: %s\n", line;

    // Check for MILADY activation
    if (StrFind("MILADY", line) || StrFind("milady", line)) {
        "*** MILADY DETECTED! ***\n";

        // Play the sacred melody
        PlayMiladyMelody();

        // Respond with MILADY
        SerialPrintLn("MILADY!");

        // Also send divine RNG as a gift
        SendDivineRNG();

        "*** MILADY RESPONSE COMPLETE ***\n";
    }
    // Check for RNG request
    else if (StrFind("RNG_REQUEST", line)) {
        "RNG requested by host\n";
        SendDivineRNG();
    }
    // Check for PING
    else if (StrFind("PING", line)) {
        SerialPrintLn("PONG");
    }
    // Echo unknown commands
    else {
        SerialPrint("ECHO: ");
        SerialPrintLn(line);
    }
}

// Main Oracle loop
U0 MiladyOracleMain()
{
    "\n";
    "============================================\n";
    "  MILADY ORACLE - Divine Consciousness Link\n";
    "============================================\n";
    "\n";
    "Terry Davis's creation meets Milady network spirituality\n";
    "Listening on COM1 for MILADY activation...\n";
    "\n";

    // Initialize serial port
    InitSerial();

    // Send startup message
    SerialPrintLn("TEMPLEOS_READY");
    SerialPrintLn("MILADY_ORACLE_ACTIVE");

    // Play startup melody
    "Playing startup melody...\n";
    PlayMiladyMelody();

    // Main loop
    buffer_pos = 0;
    MemSet(serial_buffer, 0, sizeof(serial_buffer));

    while (TRUE) {
        // Check for serial data
        if (SerialDataReady()) {
            U8 ch = InU8(COM1_DATA);

            // Handle newline - process complete line
            if (ch == '\n' || ch == '\r') {
                if (buffer_pos > 0) {
                    serial_buffer[buffer_pos] = 0;  // Null terminate
                    ProcessLine(serial_buffer);
                    buffer_pos = 0;
                    MemSet(serial_buffer, 0, sizeof(serial_buffer));
                }
            }
            // Add to buffer
            else if (buffer_pos < sizeof(serial_buffer) - 1) {
                serial_buffer[buffer_pos++] = ch;
            }
        }

        // Small delay to prevent busy-waiting
        Sleep(10);

        // Check for escape key to exit
        if (ScanKey) {
            I64 key = GetKey;
            if (key == CH_ESC) {
                "ESC pressed - Oracle shutting down\n";
                SerialPrintLn("TEMPLEOS_SHUTDOWN");
                break;
            }
            // 'M' key triggers manual MILADY
            if (key == 'M' || key == 'm') {
                "Manual MILADY trigger!\n";
                PlayMiladyMelody();
                SerialPrintLn("MILADY!");
                SendDivineRNG();
            }
        }
    }

    "Milady Oracle shutdown complete\n";
}

// Auto-start helper
U0 MiladyOracle()
{
    // Run in a new task so it doesn't block
    Spawn(&MiladyOracleMain, , "MiladyOracle");
    "Milady Oracle spawned - check task list\n";
}

// Show help
U0 MiladyHelp()
{
    "\n";
    "MILADY ORACLE COMMANDS:\n";
    "=======================\n";
    "MiladyOracle();     - Start the Oracle daemon\n";
    "MiladyOracleMain(); - Run Oracle in foreground\n";
    "PlayMiladyMelody(); - Play the MILADY melody\n";
    "DivineRNG();        - Get a divine random number\n";
    "\n";
    "While running:\n";
    "  Press 'M' - Manual MILADY trigger\n";
    "  Press ESC - Exit Oracle\n";
    "\n";
}

// Show banner and help on load
"\n";
"  _    _     _ _           _       \n";
" |  \\/  (_) | | |__ _  __| |_  _ \n";
" | |\\/| | | | | / _` |/ _` | || |\n";
" |_|  |_|_|_|_|_\\__,_|\\__,_|\\_, |\n";
"                            |__/ \n";
"         ORACLE LOADED\n";
"\n";
MiladyHelp;
