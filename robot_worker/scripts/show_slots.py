"""Robot shows each slot: lowers the open gripper to down_sN so the keyring can be placed exactly there."""
import sys, threading, time
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from worker.robot import SO101, GRIPPER, load_poses

P = {k: {j: v for j, v in p.items() if j != GRIPPER} for k, p in load_poses()["poses"].items()}
arm = SO101(cameras=False)
stop = threading.Event()
SPEED = 0.4
try:
    input("\n[0] TAY RA KHOI BAN. Bam Enter: robot ve tu the nghi va mo kep...")
    arm.move_to(P["home"], stop, SPEED); arm.gripper(38, stop)
    if "--slot4" in sys.argv:
        # Slot 4 (parking): the camera records where a keyring sits there, so picks at slot 4 can
        # be lined up like slots 1-3. Needs the side camera to see slot 4.
        input("\n[O 4] O 4 phai TRONG. TAY RA KHOI BAN. Bam Enter: robot ha kep xuong o 4...")
        arm.move_to(P["above_s4"], stop, SPEED); arm.move_to(P["down_s4"], stop, SPEED)
        input("  -> Tam dat moc khoa DEN VAO GIUA 2 NGON KEP o o 4. Rut tay ra roi bam Enter...")
        arm.move_to(P["above_s4"], stop, SPEED); arm.move_to(P["home"], stop, SPEED)
        import cv2, json, os
        from worker.robot import POSES_FILE
        from worker.row_check import find_xy
        cap = cv2.VideoCapture(int(os.getenv("SIDE_CAMERA_INDEX", "0")))
        seen = None
        for _ in range(30):
            ok, f = cap.read()
            if ok:
                xy = find_xy(f)
                if "black" in xy:
                    seen = xy["black"]
        cap.release()
        if seen:
            d = json.loads(POSES_FILE.read_text()); d["slot4_cal"] = [round(seen[0], 4), round(seen[1], 4)]
            POSES_FILE.write_text(json.dumps(d, indent=2) + "\n")
            print(f"  camera thay o 4 tai x={seen[0]:.3f}  (da luu)")
        else:
            print("  !! camera KHONG thay moc khoa o o 4: chinh camera roi chay lai.")
        input("  -> Lay moc khoa den ra khoi o 4 (o 4 de trong). Bam Enter...")
    for n in (1, 2, 3):
        input(f"\n[O {n}] Lay moc khoa ra khoi o {n}. TAY RA KHOI BAN. Bam Enter: robot ha kep xuong o {n}...")
        arm.move_to(P[f"above_s{n}"], stop, SPEED); arm.move_to(P[f"down_s{n}"], stop, SPEED)
        input(f"  -> Dat moc khoa (o 1 den, o 2 trang, o 3 tim) VAO GIUA 2 NGON KEP, chinh giua.\n     Rut tay ra roi bam Enter...")
        arm.move_to(P[f"above_s{n}"], stop, SPEED)
    arm.move_to(P["home"], stop, SPEED)
    print("\nXONG. Ban o vi tri ban dau: o 1 den, o 2 trang, o 3 tim, o 4 trong. Camera se tu ghi nho vi tri. Dong cua so nay.")
finally:
    arm.disconnect()
