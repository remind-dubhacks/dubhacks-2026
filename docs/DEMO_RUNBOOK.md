# Demo: robot đổi chỗ móc khóa (hướng dẫn ngắn)

Robot chạy **theo kịch bản** (vị trí đã dạy, camera kiểm tra), không dùng mô hình AI. Hãy nói rõ điều này khi demo. Đã kiểm chứng trên cánh tay (18/10, 05:00): **swap_lr** và **swap_lm**, cả hai chiều, camera xác nhận.

**Quy tắc quan trọng nhất:** chỉ đặt bàn bằng `scripts/show_slots.py` (robot chỉ chỗ), không bao giờ đặt bằng tay. Đặt bằng tay thì móc khóa lệch cả xa–gần, robot không bù được, và gần như lần nào cũng hụt.

## Trước khi demo (5 phút)

1. **Đặt bàn:** đen · trắng · tím ở ô 1–3, ô 4 trống. Đừng đặt bằng tay theo trí nhớ: chạy `uv run python scripts/show_slots.py` (worker tắt) để móc khóa nằm đúng chỗ robot gắp, rồi bật worker và chạy lệnh hiệu chỉnh camera ở mục "Khi có sự cố".
2. **Đừng chạm vào camera bên hông.** Lệch camera thì các vị trí cũng lệch theo.
3. **Kiểm tra camera đúng thiết bị:** chỉ cắm camera bên hông (C920) và camera cổ tay; tắt iPhone Continuity Camera. Thứ tự camera trên Mac có thể bị đổi.
4. **Bật worker** (từ Terminal.app, để có quyền dùng camera):

   ```bash
   cd ~/dubhacks-2026/robot_worker && uv run uvicorn worker.main:app --port 8001
   ```

5. **Kiểm tra:** `curl -s localhost:8001/health` phải ra `"mode":"scripted","ready":true`. Còn `curl -s localhost:8001/studio/vision/row` phải ra `"order":["black","white","purple"]`.
6. Một người **đứng ở nút dừng khẩn cấp** suốt buổi demo.

## Chạy demo

Trong thư mục `robot_worker`:

| Lệnh | Robot làm gì | Bàn trước → sau |
|---|---|---|
| `scripts/demo.sh swap_lr` | đổi chỗ trái và phải | đen·trắng·tím → tím·trắng·đen |
| `scripts/demo.sh swap_lr back` | trả về ban đầu | tím·trắng·đen → đen·trắng·tím |
| `scripts/demo.sh swap_lm` | đổi chỗ trái và giữa | đen·trắng·tím → trắng·đen·tím |
| `scripts/demo.sh swap_lm back` | trả về ban đầu | trắng·đen·tím → đen·trắng·tím |

Mỗi lần chạy mất khoảng 1–2 phút. Sau khi chạy, script in **RESULT: SUCCEEDED** (camera xác nhận đúng thứ tự) hoặc lý do dừng.

**Giữa các lần chạy, không đặt lại móc khóa bằng tay.** Để robot tự trả về bằng lệnh `back`.

## Robot tự dừng khi nào (đây là các tính năng an toàn, hãy khoe chúng)

- **Có tay trên bàn:** robot đứng yên, nói *"I'll wait while your hand is on the table"*, rồi chạy tiếp khi bàn trống 1,5 giây.
- **Móc khóa không đúng thứ tự** trước khi chạy: `start_mismatch`, robot không di chuyển.
- **Móc khóa lệch chỗ gắp:** `keyring_off_spot`, kèm câu chỉ cần đẩy móc khóa về hướng nào.
- **Gắp hụt:** robot thử lại một lần. Nếu vẫn hụt thì `grasp_missed`, robot dừng **trước khi đặt**, để không xô móc khóa khác.
- **Kết quả sai:** camera so thứ tự cuối với kết quả mong đợi (`shuffle_mismatch`).
- **Nút dừng khẩn cấp:** luôn là cách an toàn chính. Dừng bằng phần mềm: `curl -X POST localhost:8001/stop`.

## Khi có sự cố

- **Móc khóa lệch hoặc đổ:** lấy hết móc khóa ra, chạy cửa sổ "robot chỉ chỗ", rồi hiệu chỉnh camera:

  ```bash
  curl -s -X POST localhost:8001/studio/vision/calibrate-slots -H 'Content-Type: application/json' -d '{}'
  ```

  Cửa sổ "robot chỉ chỗ": dừng worker (Ctrl+C trong cửa sổ worker), rồi chạy `uv run python scripts/show_slots.py` trong `robot_worker`. Robot hạ kẹp mở xuống từng ô, bạn đặt móc khóa vào giữa hai ngón kẹp và bấm Enter. Sau đó bật lại worker và chạy lệnh hiệu chỉnh ở trên.
- **Worker không khởi động, báo "Missing motor IDs: 6":** cờ quá tải của kẹp. Rút điện follower 10 giây, cắm lại, rồi bật lại worker.
- **Kẹp nóng từ 60 °C trở lên:** nghỉ vài phút trước khi chạy tiếp.

## Chưa ổn định (đừng demo)

- **Ô 4 (chỗ đậu tạm) là điểm yếu.** Mọi kiểu đổi chỗ đều đặt một móc khóa ở ô 4 rồi gắp lại, nhưng camera không nhìn thấy ô 4. Với bộ vị trí tốt nhất (đang dùng), lần gắp lại ở ô 4 thành công **5/7**. Các biến thể khác (dạy lại kẹp thẳng, vị trí trung vị từ dữ liệu, kẹp mở rộng 55%) đều kém hơn. Khi gắp hụt, robot dừng an toàn và báo `grasp_missed`.
- **swap_mr, rot_left, rot_right:** chưa có lượt nào chạy trọn vẹn (đều vướng ô 4).
- **Cách tốt nhất tiếp theo:** dời camera bên hông để thấy cả ô 4, rồi bật chỉnh góc bằng camera cho ô 4 như ô 1–3.
- **Mô hình AI (v1, v2, mỗi cái 1000 bước):** cánh tay di chuyển êm và an toàn (không lệnh nào vượt giới hạn khớp), nhưng chưa gắp được. v2 còn **gạt móc khóa lệch khỏi chỗ** (thử lúc 06:00). Vì vậy chế độ kết hợp (AI thử trước, kịch bản hoàn thành; `HYBRID_SCRIPTED=1` với `ROBOT_MODE=perceptron`) đang **tắt**: sau khi AI thử, kịch bản không gắp được nữa. Cần huấn luyện lâu hơn (10.000 bước) và thêm dữ liệu. Để giới hạn robot chỉ chạy 2 kiểu đã kiểm chứng, đặt `ROBOT_SHUFFLES=swap_lr,swap_lm` trong `robot_worker/.env` rồi khởi động lại worker.
