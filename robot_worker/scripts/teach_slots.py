"""Teach the pick/place movement for all 4 slots by hand: for each slot, down (gripper open around the
keyring, base on the table) and above (straight up ~5 cm). Saves into poses.json."""
import sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from worker.robot import SO101, load_poses, save_poses

arm = SO101(cameras=False)
try:
    data = load_poses()
    print("\n=== DAY LAI GAP/DAT CHO 4 O ===")
    print("Dat 1 moc khoa (vd: den) DUNG THANG o o can day. Day o 1, roi chuyen moc khoa sang o 2, 3, 4.")
    print("Moi o: KEP MO, THANG DUNG, cung huong nhu nhau o ca 4 o.")
    input("Mot tay do canh tay FOLLOWER. Bam Enter: luc tat, canh tay mem ra...")
    arm.torque(False)
    slots = [int(a) for a in sys.argv[1:] if a.isdigit()] or [1, 2, 3, 4]
    for n in slots:
        if n == 4:
            print("  (O 4 = o TRONG cuoi hang, sau o 3, cach o 3 bang khoang cach giua o 2 va o 3)")
        input(f"\n[O {n}] Dat moc khoa dung o o {n}. Ha kep MO xuong OM moc khoa, day moc khoa cham ban,\n"
              f"       kep thang dung, khong cham ban. Giu yen, bam Enter (luu down_s{n})...")
        data["poses"][f"down_s{n}"] = {k: round(v, 2) for k, v in arm.joints().items()}
        input(f"[O {n}] NHAC THANG LEN ~5 cm (khong xoay de, khong nghieng). Giu yen, bam Enter (luu above_s{n})...")
        data["poses"][f"above_s{n}"] = {k: round(v, 2) for k, v in arm.joints().items()}
        d, a = data["poses"][f"down_s{n}"], data["poses"][f"above_s{n}"]
        print(f"   o {n}: co tay {d['wrist_flex.pos']:.0f}, xoay {d['wrist_roll.pos']:.0f}, nhac len {d['shoulder_lift.pos'] - a['shoulder_lift.pos']:.0f} do")
    for k in ("camera_x", "camera_xy", "slot4_cal", "demo_ranges"):
        data.pop(k, None)
    data["_note"] = f"Slot poses re-taught by hand (teach_slots.py, slots {slots})."
    save_poses(data)
    input("\nDo canh tay. Bam Enter: luc bat lai...")
    arm.torque(True)
    print("XONG. Da luu 8 vi tri. Dong cua so nay va nhan Claude.")
finally:
    arm.disconnect()
