# Projector Add-on for Blender
Simple projector creation and modification for [Blender](https://www.blender.org/).

![Projector Add-on for Blender title image](/.github/gifs/title.jpg)

## What this Add-on can do for you
* Easy creation and modification of physically-based projectors.
* Real-world projector settings like [throw ratio](https://en.wikipedia.org/wiki/Throw_(projector)), [resolution](https://en.wikipedia.org/wiki/Computer_display_standard) and [lens shift](https://www.projectorcentral.com/Understanding-Lens-Offset-and-Lens-Shift.htm).
* Project test textures or your own content like images and videos.
* Preview the projections in Cycles render mode (Eevee will be supported when the needed functionality is implemented).

## Projectors Add-on in Action

#### Throw Ratio
Control the size of your projection by adjusting the throw ratio to match real-world projector specifications.
![Throw Ratio](/.github/gifs/throw_ratio.gif)

#### Lens Shift
Fine-tune the vertical and horizontal position of your projection without moving the projector itself.
![Lens Shift](/.github/gifs/lens_shift.gif)

#### Image Textures & Resolution
Load your own images or videos and set custom resolutions to match your projection content.
![Image Texture & Resolutions](/.github/gifs/image_textures_resolution.gif)

#### Image Mapping (corner pin, transform, crop)
Map the projected image onto your set the way a media server would, directly in Blender.
Find it in the **Image Mapping** sub-panel of the Projector panel.

* **Corner Pin / keystone** – move the four corners of the image inside the projector frame
  (normalized coordinates, `0,0` is bottom-left of the frame and `1,1` top-right).
  * **Pin Corners to Face** – select the projector and a mesh, and the four corners snap to the
    selected quad face (or the first quad of the mesh). The image lands exactly on that surface.
  * **Pin Corner to 3D Cursor** – snap the 3D cursor to a vertex of your set and pin the active corner there.
  * **Nudge** – move the active corner by projector pixels for fine adjustment.
* **Transform** – offset, uniform/non-uniform scale, rotation (aspect-correct) and flip of the
  image inside the pinned area. Anything outside is black.
* **Crop** – use only a region of the source image (left/right/top/bottom %), handy for splitting
  one piece of content across several projectors.

![Mapping tests](/docs/capturas/01-mapping-pruebas.png)

Works with the checker, color grid and custom image/movie modes. Projectors created with older
versions of the add-on are upgraded automatically the first time a mapping value changes.

#### Random Color
Quickly assign random colors to distinguish multiple projectors in your scene.
![Random Color](/.github/gifs/random_color.gif)

## Note
* works with Blender 2.8 and up

## Wiki
* A growing [wiki](https://github.com/Ocupe/Projectors/wiki) to help users with this add-on. If you have problems or feel that something is missing, please feel free to request more content.

## Installation
* Download the repo by clicking the green **Code** button and then **Download ZIP** (don't unpack the file on your computer).
* Open Blender.
* Go to the User Preferences in the Addon tab.
* Click Install from File and choose the zip file you downloaded.
* Activate the add-on by clicking on the checkbox.

## Missing something?
I'm interested and open to suggestions. Let me know how you use the add-on and how it could improve. Open an issue or message me.

P.S. Germans like to call a projector, a beamer.

## Créditos / Credits
Projector add-on: Jonas Schell (Ocupe) — https://github.com/Ocupe/Projectors

Image mapping (corner pin, transform, crop):  
Diseño, investigación y desarrollo: Héctor Cruz Juárez — https://hectorcruz.com.mx  
Colección Alchemy of Meaning.

License: GPL-3.0-or-later (same as the original add-on).
