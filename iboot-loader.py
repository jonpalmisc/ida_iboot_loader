import idautils
import idaapi
import ida_idaapi
import ida_search
import ida_funcs
import ida_bytes
import ida_idp
import idc

PROLOGUES = ["7F 23 03 D5", "BD A9", "BF A9"]


def set_name_from_str_xref(base_addr, name, string):
    """Set function name based on a string xref."""
    string_offset = ida_search.find_text(
        base_addr, 1, 1, string, ida_search.SEARCH_DOWN
    )
    if string_offset == ida_idaapi.BADADDR:
        return ida_idaapi.BADADDR

    xref = list(idautils.XrefsTo(string_offset))
    if len(xref) == 0:
        return ida_idaapi.BADADDR

    function = idaapi.get_func(xref[0].frm)
    if function is None:
        return ida_idaapi.BADADDR

    idc.set_name(function.start_ea, name, idc.SN_CHECK)
    print(f"[+] {name} : {hex(function.start_ea)}")
    return function.start_ea


def set_name_from_pattern_xref(base_addr, end, name, pattern):
    """Set function name based on a specific bytes pattern."""
    pattern_offset = ida_search.find_binary(
        base_addr, end, pattern, 16, ida_search.SEARCH_DOWN
    )
    if pattern_offset == ida_idaapi.BADADDR or pattern_offset is None:
        return ida_idaapi.BADADDR

    xref = list(idautils.XrefsTo(pattern_offset))
    if len(xref) == 0:
        return ida_idaapi.BADADDR

    function = idaapi.get_func(xref[0].frm)
    if function is None:
        return ida_idaapi.BADADDR
    idc.set_name(function.start_ea, name, idc.SN_CHECK)
    print(f"[+] {name} : {hex(function.start_ea)}")
    return function.start_ea


def set_name_from_func_xref(base_addr, name, function_addr):
    """Set function name based on a function xref."""
    if function_addr == ida_idaapi.BADADDR:
        return ida_idaapi.BADADDR

    xref_list = list(idautils.XrefsTo(function_addr))
    if len(xref_list) == 0:
        return ida_idaapi.BADADDR

    function = ida_funcs.get_func(xref_list[0].frm)
    if function is None:
        return ida_idaapi.BADADDR

    idc.set_name(function.start_ea, name, idc.SN_CHECK)
    print(f"[+] {name} : {hex(function.start_ea)}")
    return function.start_ea


def set_name_on_str_before_bl(name: str, string: str):
    """Set name according to string before BL inst.
    Example with printf, we look for "USB_SERIAL_NUMBER:" then find the next BL.
    It branches to printf.
    ADR             X0, aUsbSerialNumbe ; "::\tUSB_SERIAL_NUMBER: %s\n"
    NOP
    BL              sub_1800F4980 <- printf

    TODO: maybe find a better name
    """
    string_offset = ida_search.find_text(0, 1, 1, string, ida_search.SEARCH_DOWN)

    if string_offset == ida_idaapi.BADADDR:
        return ida_idaapi.BADADDR

    xref = list(idautils.XrefsTo(string_offset))
    if len(xref) == 0:
        return ida_idaapi.BADADDR

    function = idaapi.get_func(xref[0].frm)
    for addr in range(xref[0].frm, idc.find_func_end(function.start_ea)):
        insn = idc.print_insn_mnem(addr)
        if "BL" in insn:
            function_addr = f"0x{idc.print_operand(addr, 0).split('_')[1]}"
            function = idaapi.get_func(int(function_addr, 16))
            print(f"[+] {name} : {hex(function.start_ea)}")
            idc.set_name(function.start_ea, name, idc.SN_CHECK)
            return function.start_ea


def set_name_on_xref_asserts(functions_list: list) -> list:
    """In A12+ dev iBoots we have strings like 'ASSERT (%s:%d)\n'
    at xref_addr-8 you can find the name of the function used by assert. Eg:
    ADR             X0, aArchTaskFreeSt ; "arch_task_free_stack"
    NOP
    ADR             X1, aAssertSD ; "ASSERT (%s:%d)\n"
    """
    assert_str = idc.get_name_ea_simple("aAssertSD")
    xrefs = idautils.XrefsTo(assert_str)
    for xref in xrefs:
        addr = xref.frm
        function = ida_funcs.get_func(xref.frm)
        if function is None or "sub_" not in ida_funcs.get_func_name(xref.frm):
            continue
        dis = idc.GetDisasm(addr - 8)
        if "X0, a" in dis:
            operand = idc.print_operand(addr - 8, 1)
            string_name_addr = idc.get_name_ea_simple(operand)
            name = idc.get_strlit_contents(string_name_addr).decode()

            # if name already exists, continue
            if f"_{name}" in functions_list:
                continue
            print(f"[+] _{name} : {hex(function.start_ea)}")
            idc.set_name(function.start_ea, f"_{name}", idc.SN_NOWARN)
            # use idc.SN_NOWARN if there are to many warnings
            functions_list.append(f"_{name}")
    return functions_list


def set_name_on_xref_heap_malloc(heap_malloc: int):
    """Debug iBoots use heap_malloc(size_t size, const char *caller_name).
    We can use it to get the name of the function which calls it.
    Only tested on one debug iBoot (from A10/iOS10), it may not be 100% accurate.
    """
    xrefs = idautils.XrefsTo(heap_malloc)
    for xref in xrefs:
        addr = xref.frm
        function = ida_funcs.get_func(addr)
        # check that the function hasn't already a name
        if function is None or "sub_" not in ida_funcs.get_func_name(xref.frm):
            continue

        # find the name of heap_malloc caller
        for i in range(addr, addr - 20, -4):
            dis = idc.GetDisasm(i)
            if "BL" in dis and i != addr:
                break

            if "ADRX1,a" in dis.replace(" ", ""):
                operand = idc.print_operand(i, 1)
                string_name_addr = idc.get_name_ea_simple(operand)
                name = idc.get_strlit_contents(string_name_addr).decode()
                print(f"[+] _{name} : {hex(function.start_ea)}")
                idc.set_name(function.start_ea, f"_{name}")


def set_name_on_xref_panics(panic) -> list:
    """Same as previous function but for panic xrefs."""
    xrefs = idautils.XrefsTo(panic)
    functions_list = []
    for xref in xrefs:
        addr = xref.frm
        function = ida_funcs.get_func(xref.frm)
        if function is None or "sub_" not in ida_funcs.get_func_name(xref.frm):
            continue

        expected_nop = idc.print_insn_mnem(addr - 4)
        dis = idc.GetDisasm(addr - 16)
        if expected_nop == "NOP" and ("X0, a" in dis and "#0" not in dis[-2:]):
            # if we have a line like this : "ADR X0, aPlatformQuiesc"
            # it returns "aPlatformQuiesc"
            operand = idc.print_operand(addr - 16, 1)
            string_name_addr = idc.get_name_ea_simple(operand)
            name = idc.get_strlit_contents(string_name_addr).decode()

            if f"_{name}" in functions_list:
                continue

            print(f"[+] _{name} : {hex(function.start_ea)}")
            idc.set_name(function.start_ea, f"_{name}")
            functions_list.append(f"_{name}")
    return functions_list


def accept_file(fd, fname):
    """Make sure file is valid."""
    fd.seek(0x200)
    try:
        image_type = fd.read(0x30).decode()
    except UnicodeDecodeError:
        return 0

    if image_type[:5] == "iBoot" or image_type[:4] in ["iBEC", "iBSS"]:
        return {"format": "iBoot (AArch64)", "processor": "arm"}

    if image_type[:9] in ["SecureROM", "AVPBooter"]:
        return {"format": "SecureROM (AArch64)", "processor": "arm"}
    return 0


def is_bootrom(fd) -> bool:
    """Check if image is rom type. Purely aesthetic."""
    fd.seek(0x200)
    image_type = fd.read(0x30).decode()
    if image_type[:9] in ["SecureROM", "AVPBooter"]:
        return True
    return False


def is_bootloader_release(fd) -> [bool, str]:
    """Check if bootloader is type release."""
    tags = [b"RELEASE", b"ROMRELEASE", b"RESEARCH_RELEASE", b"DEBUG", b"DEVELOPMENT"]
    fd.seek(0x240)
    data = fd.read(16)
    for tag in tags:
        tag_len = len(tag)
        data_ = data[:tag_len]
        if data_ == tag and data_ in tags[:3]:
            return True, tag.decode()
        elif data_ == tag and data not in tags[:3]:
            return False, tag.decode()
    return False, None


def load_file(fd, neflags, format):
    """Function to load file."""
    size = 0
    base_addr = 0

    idaapi.set_processor_type("arm", ida_idp.SETPROC_LOADER_NON_FATAL)
    idaapi.get_inf_structure().lflags |= idaapi.LFLG_64BIT

    if (neflags & idaapi.NEF_RELOAD) != 0:
        return 1

    fd.seek(0, idaapi.SEEK_END)
    size = fd.tell()

    segm = idaapi.segment_t()
    segm.bitness = 2  # 64-bit
    segm.start_ea = 0
    segm.end_ea = size

    if is_bootrom(fd):
        idaapi.add_segm_ex(segm, "SecureROM", "CODE", idaapi.ADDSEG_OR_DIE)
    else:
        idaapi.add_segm_ex(segm, "iBoot", "CODE", idaapi.ADDSEG_OR_DIE)

    bl_data = is_bootloader_release(fd)
    print(f"[i] bootloader : {bl_data[1]}")

    fd.seek(0)
    fd.file2base(0, 0, size, False)

    idaapi.add_entry(0, 0, "start", 1)
    ida_funcs.add_func(0)

    for addr in range(0, 0x200, 4):
        insn = idc.print_insn_mnem(addr)
        if "LDR" in insn:
            base_str = idc.print_operand(addr, 1)
            base_addr = int(base_str.split("=")[1], 16)
            break

    if base_addr == 0:
        print("[!] Failed to find base address, it's now set to 0x0")

    print(f"[+] Rebasing to address {hex(base_addr)}")
    idaapi.rebase_program(base_addr, idc.MSF_NOFIX)

    segment_end = idc.get_segm_attr(base_addr, idc.SEGATTR_END)

    for prologue in PROLOGUES:
        while addr != ida_idaapi.BADADDR:
            addr = ida_search.find_binary(
                addr, segment_end, prologue, 16, ida_search.SEARCH_DOWN
            )
            if addr != ida_idaapi.BADADDR:
                if len(prologue) < 8:
                    addr = addr - 2

                if (addr % 4) == 0 and ida_bytes.get_full_flags(addr) < 0x200:
                    ida_funcs.add_func(addr)
                addr += 4

    idc.plan_and_wait(base_addr, segment_end)

    # find IMG4 string as byte
    set_name_from_pattern_xref(
        base_addr, segment_end, "_image4_get_partial", "49 4d 47 34"
    )

    set_name_from_str_xref(base_addr, "_do_printf", "<null>")
    panic = set_name_from_str_xref(base_addr, "_panic", "double panic in")
    set_name_from_str_xref(base_addr, "_platform_get_usb_serial_number_string", "CPID:")
    set_name_from_str_xref(base_addr, "_platform_get_usb_more_other_string", " NONC:")
    set_name_from_str_xref(base_addr, "_UpdateDeviceTree", "fuse-revision")
    set_name_from_str_xref(base_addr, "_main_task", "debug-uarts")
    set_name_from_str_xref(base_addr, "_platform_init_display", "backlight-level")
    set_name_from_str_xref(base_addr, "_do_printf", "<null>")
    set_name_from_str_xref(base_addr, "_do_memboot", "Combo image too large")
    set_name_from_str_xref(base_addr, "_do_go", "Memory image not valid")
    set_name_from_str_xref(base_addr, "_task_init", "idle task")
    set_name_from_str_xref(
        base_addr,
        "_sys_setup_default_environment",
        "/System/Library/Caches/com.apple.kernelcaches/kernelcache",
    )
    set_name_from_str_xref(
        base_addr, "_check_autoboot", "aborting autoboot due to user intervention."
    )
    set_name_from_str_xref(base_addr, "_do_setpict", "picture too large, size:%zu")
    set_name_from_str_xref(
        base_addr, "_arm_exception_abort", "ARM %s abort at 0x%016llx:"
    )
    set_name_from_str_xref(base_addr, "_do_devicetree", "Device Tree image not valid")
    set_name_from_str_xref(base_addr, "_do_ramdisk", "Ramdisk image not valid")
    set_name_from_str_xref(
        base_addr,
        "_nvme_bdev_create",
        "Couldn't construct blockdev for namespace %d",
    )
    set_name_from_str_xref(base_addr, "_record_memory_range", "chosen/memory-map")
    set_name_from_str_xref(base_addr, "_boot_upgrade_system", "/boot/kernelcache")
    img4_register = set_name_from_str_xref(
        base_addr,
        "_image4_register_property_capture_callbacks",
        "image4_register_property_capture_callbacks",
    )
    set_name_from_func_xref(base_addr, "_target_init_boot_manifest", img4_register)

    set_name_from_str_xref(
        base_addr, "_target_pass_boot_manifest", "chosen/manifest-properties"
    )

    # found this one only in A12-A14-15.0 iBoot.
    set_name_from_str_xref(
        base_addr,
        "_image4_validate_property_callback_interposer",
        "Unknown ASN1 type %llu",
    )
    set_name_from_str_xref(
        base_addr, "_platform_handoff_update_devicetree", "iboot-handoff"
    )
    set_name_from_str_xref(
        base_addr, "_prepare_and_jump", "======== End of %s serial output. ========"
    )

    usb_vendor_id = set_name_from_pattern_xref(
        base_addr, segment_end, "_platform_get_usb_vendor_id", "80 b5 80 52"
    )
    usb_core_init = set_name_from_func_xref(base_addr, "_usb_core_init", usb_vendor_id)
    set_name_from_func_xref(base_addr, "_usb_init_with_controller", usb_core_init)

    set_name_on_str_before_bl("_printf", "USB_SERIAL_NUMBER:")
    set_name_on_str_before_bl("_der_expect_ia5string", "IM4P")

    heap_malloc = set_name_from_str_xref(
        base_addr, "_heap_malloc", "heap_malloc must allocate at least one byte"
    )

    functions = []
    if bl_data[0] is False:
        print("[i] looking for panic and xrefs strings...")
        functions = set_name_on_xref_panics(panic)
        set_name_on_xref_asserts(functions)

        if heap_malloc != ida_idaapi.BADADDR:
            set_name_on_xref_heap_malloc(heap_malloc)
    return 1
