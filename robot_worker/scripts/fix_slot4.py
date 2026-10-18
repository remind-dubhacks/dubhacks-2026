"""Re-teach slot 4 with the gripper straight down, then test place -> lift -> pick back at slot 4."""
import sys, threading, time
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")
from worker.robot import SO101, GRIPPER, load_poses, save_poses
from worker.shuffle_math import GRIP_CLOSE, GRIP_OPEN, GRIP_RELEASE

arm = SO101(cameras=False)
stop = threading.Event()
S = 0.4
g = lambda: round(arm.joints()["gripper.pos"], 1)
try:
    data = load_poses()
    wf = [round(data["poses"][f"down_s{n}"]["wrist_flex.pos"]) for n in (1, 2, 3)]
    print(f"\n=== DAY LAI O 4, KEP THANG DUNG (o 1-3 co co tay ~{wf} do) ===")
    print("Dat moc khoa DEN dung thang o o 4. Cac o khac de nguyen.")
    input("Mot tay do canh tay FOLLOWER. Bam Enter: luc tat...")
    arm.torque(False)
    input("\n[down_s4] Ha kep MO xuong om moc khoa den o o 4. KEP THANG DUNG, vuong goc mat ban\n"
          "          (giong luc o o 2, o 3). Day moc khoa cham ban. Giu yen, bam Enter...")
    d = {k: round(v, 2) for k, v in arm.joints().items()}
    input("[above_s4] NHAC THANG LEN ~5 cm, giu kep thang dung. Bam Enter...")
    a = {k: round(v, 2) for k, v in arm.joints().items()}
    print(f"   co tay (wrist_flex): down {d['wrist_flex.pos']}, above {a['wrist_flex.pos']}")
    data["poses"]["down_s4"], data["poses"]["above_s4"] = d, a
    save_poses(data)
    input("\nDo canh tay. Bam Enter: luc bat lai...")
    arm.torque(True)

    P = {k: {j: v for j, v in p.items() if j != GRIPPER} for k, p in load_poses()["poses"].items()}
    input("\n=== THU O 4: robot gap moc khoa den o o 4, nhac len, dat lai, nhac len, gap lai ===\n"
          "TAY RA KHOI BAN. Bam Enter...")
    arm.move_to(P["home"], stop, S); arm.gripper(GRIP_OPEN, stop)
    results = []
    for i in range(3):
        arm.move_to(P["above_s4"], stop, S); arm.move_to(P["down_s4"], stop, S)
        arm.gripper(GRIP_CLOSE, stop); time.sleep(0.4)
        held = g(); results.append(held)
        print(f"  lan {i + 1}: kep doc {held} -> {'GIU DUOC' if held >= 15.5 else 'HUT'}")
        if held < 15.5:
            arm.gripper(GRIP_OPEN, stop); arm.move_to(P["above_s4"], stop, S)
            break
        arm.move_to(P["above_s4"], stop, S)          # lift it
        arm.move_to(P["down_s4"], stop, S)           # put it back down
        arm.gripper(GRIP_RELEASE, stop); time.sleep(0.4)
        arm.move_to(P["above_s4"], stop, S)          # release and lift (this is where it used to shift)
        arm.gripper(GRIP_OPEN, stop)
    arm.move_to(P["home"], stop, S)
    print(f"\nKET QUA: {results}. Nhan ket qua cho Claude. Dong cua so nay.")
finally:
    arm.disconnect()
