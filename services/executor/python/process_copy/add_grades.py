import cv2
from pdf2image import convert_from_path
import img2pdf
import numpy as np
import os
import sys
from process_copy.recognize import add_grades

input_pdf_path = '../../../../storage/cover_pages/front_box.pdf'
output_pdf_path = '../../storage/cover_pages/output_pdf_with_numbers.pdf'
intermediate_image_path = '../../images/intermediate_image.png'

shape=(8.5, 11)
dpi=300
shape = (int(dpi * shape[0]), int(dpi * shape[1]))

numbers = ['5', '8', '7', '9', '6', '35']
add_grades(numbers, input_pdf_path, (0.8, .95, 0.2, 0.55), add_border=False, shape=shape)

# image = convert_from_path(intermediate_image_path)
#
# image = np.array(images[0])
#
# image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

# positions = [
#     (1500, 550),
#     (1500, 620),
#     (1500, 700),
#     (1500, 780),
#     (1500, 860),
#     (1500, 940),
#     (1500, 1020)
# ]

# font = cv2.FONT_HERSHEY_SIMPLEX
# font_scale = 1
# color = (0, 0, 255)
# thickness = 2
#
# for pos, num in zip(positions, numbers):
#     cv2.putText(image, num, pos, font, font_scale, color, thickness)
#
# cv2.imwrite(intermediate_image_path, image)

# Open the image file in binary mode and convert it to PDF
with open(intermediate_image_path, "rb") as image_file:
    image_data = image_file.read()
    pdf_bytes = img2pdf.convert(image_data)

# Write the PDF bytes to the output file
with open(output_pdf_path, "wb") as f:
    f.write(pdf_bytes)

# Clean up intermediate image file
# os.remove(intermediate_image_path)

print(f"Processed PDF saved as {output_pdf_path}")
