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
    for n in (1, 2, 3):
        input(f"\n[O {n}] Lay moc khoa ra khoi o {n}. TAY RA KHOI BAN. Bam Enter: robot ha kep xuong o {n}...")
        arm.move_to(P[f"above_s{n}"], stop, SPEED); arm.move_to(P[f"down_s{n}"], stop, SPEED)
        input(f"  -> Dat moc khoa (o 1 den, o 2 trang, o 3 tim) VAO GIUA 2 NGON KEP, chinh giua.\n     Rut tay ra roi bam Enter...")
        arm.move_to(P[f"above_s{n}"], stop, SPEED)
    arm.move_to(P["home"], stop, SPEED)
    print("\nXONG. Ban o vi tri ban dau: o 1 den, o 2 trang, o 3 tim, o 4 trong. Camera se tu ghi nho vi tri. Dong cua so nay.")
finally:
    arm.disconnect()
