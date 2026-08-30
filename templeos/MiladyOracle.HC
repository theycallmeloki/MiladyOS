/*
 * MiladyOracle.HC - Divine consciousness bridge for TempleOS
 *
 * Runs inside TempleOS V5.050 via templeos-loader (Linux userspace,
 * no QEMU, no ISO). Communicates with the host over stdio through
 * the loader's vsyscall layer:
 *   - VSYSCALL_READ (9) reads stdin (fd 0)
 *   - "..." string output goes to stdout via RawPutChar -> PUTCHAR
 *
 * Protocol (line-based over stdin/stdout):
 *   TEMPLEOS_READY          - sent at startup
 *   MILADY                  - triggers MILADY! + divine RNG response
 *   RNG_REQUEST             - returns RNG:<n>
 *   PING                    - returns PONG
 *   anything else           - echoed as ECHO:<line>
 *
 * Terry Davis would approve - no abstractions between you and God.
 */

#include "::/AdamInit"

public _extern _VSYSCALL I64 VSysCall(I64 num, I64 arg1, I64 arg2, I64 arg3, I64 arg4);

U0 SendDivineRNG()
{
    "RNG:%d\n", RandU64;
}

U0 ProcessLine(U8 *line)
{
    if (StrFind("MILADY", line) || StrFind("milady", line)) {
        "MILADY!\n";
        SendDivineRNG();
    } else if (StrFind("RNG_REQUEST", line)) {
        SendDivineRNG();
    } else if (StrFind("PING", line)) {
        "PONG\n";
    } else {
        "ECHO:%s\n", line;
    }
}

U0 MiladyOracleMain()
{
    U8 line_buf[256];
    I64 line_pos = 0;
    U8 ch;

    "TEMPLEOS_READY\n";
    "MILADY_ORACLE_ACTIVE\n";

    while (TRUE) {
        ch = 0;
        if (VSysCall(9, 0, &ch, 1, 0) <= 0) {   // VSYSCALL_READ = 9
            "TEMPLEOS_SHUTDOWN\n";
            break;
        }
        if (ch == '\n' || ch == '\r') {
            if (line_pos > 0) {
                line_buf[line_pos] = 0;
                ProcessLine(line_buf);
                line_pos = 0;
            }
        } else if (line_pos < sizeof(line_buf) - 1) {
            line_buf[line_pos++] = ch;
        }
    }
}

MiladyOracleMain;
