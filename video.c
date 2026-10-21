/* -*- mode: c; tab-width: 4; c-basic-offset: 4; c-file-style: "linux" -*- */
//
// Copyright (c) 2009-2011, Wei Mingzhi <whistler_wmz@users.sf.net>.
// Copyright (c) 2011-2020, SDLPAL development team.
// All rights reserved.
//
// This file is part of SDLPAL.
//
// SDLPAL is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <http://www.gnu.org/licenses/>.
//
#include <float.h>
#include "main.h"

// Screen buffer
SDL_Surface              *gpScreen           = NULL;

// Backup screen buffer
SDL_Surface              *gpScreenBak        = NULL;

// The global palette
static SDL_Palette       *gpPalette          = NULL;

#if SDL_VERSION_ATLEAST(2,0,0)
SDL_Window               *gpWindow           = NULL;
SDL_Renderer      *gpRenderer         = NULL;
SDL_Texture       *gpTexture          = NULL;
SDL_Texture       *gpTouchOverlay     = NULL;
SDL_Rect           gOverlayRect;
SDL_Rect           gTextureRect;

static struct RenderBackend {
    void (*Init)();
    void (*Setup)();
    SDL_Texture *(*CreateTexture)(int width, int height);
    void (*RenderCopy)();
} gRenderBackend;
#else
#undef PAL_HAS_GLSL
#endif

// The real screen surface
SDL_Surface       *gpScreenReal       = NULL;

volatile BOOL g_bRenderPaused = FALSE;

#ifdef UNIT_TEST
// Source-evidence capture after composition and texture upload; no gameplay UI.
VOID (*VIDEO_TestFrameHook)(VOID) = NULL;
BOOL VIDEO_TestHiddenWindow = FALSE;
#endif

static BOOL bScaleScreen = PAL_SCALE_SCREEN;

// Shake times and level
static WORD               g_wShakeTime       = 0;
static WORD               g_wShakeLevel      = 0;

// Only optional portraits allocate a companion plane. Zero is transparent,
// 0x80 tags a source-palette index, and 0xFF tags a transition's literal RGB.
// These are coverage tags, never SDL alpha blending.
static SDL_Surface *gpPortraitComposite = NULL;
static SDL_Color g_PortraitSource[256], g_PortraitCurrent[256], g_PortraitScene[256];
static BYTE g_PortraitSourceBytes[768];
static BOOL g_PortraitInitialized = FALSE, g_PortraitPaletteBound = FALSE;

VOID VIDEO_InitPortraitPalette(const BYTE palette[768])
{
   int i;
   memcpy(g_PortraitSourceBytes, palette, 768);
   for (i = 0; i < 256; ++i)
   {
      g_PortraitSource[i].r = palette[i * 3];
      g_PortraitSource[i].g = palette[i * 3 + 1];
      g_PortraitSource[i].b = palette[i * 3 + 2];
   }
   g_PortraitInitialized = TRUE;
   g_PortraitPaletteBound = FALSE;
}

static BOOL VIDEO_PortraitPaletteMatches(SDL_Surface *surface)
{
   int i;
   if (!g_PortraitPaletteBound) return FALSE;
   for (i = 0; i < 256; ++i)
   {
      SDL_Color c = surface->format->palette->colors[i];
      if (i >= 0xF9 && i <= 0xFE) continue;
      if (c.r != g_PortraitScene[i].r || c.g != g_PortraitScene[i].g ||
          c.b != g_PortraitScene[i].b) return FALSE;
   }
   return TRUE;
}

static int VIDEO_PortraitFadeLevel(SDL_Surface *surface, const SDL_Color base[256])
{
   int level, i;
   if (base == NULL) return 65;
   for (level = 0; level <= 64; ++level)
   {
      for (i = 0; i < 256; ++i)
      {
         SDL_Color c = surface->format->palette->colors[i];
         if (i >= 0xF9 && i <= 0xFE) continue;
         if (c.r != (base[i].r * level >> 6) ||
             c.g != (base[i].g * level >> 6) ||
             c.b != (base[i].b * level >> 6)) break;
      }
      if (i == 256) break;
   }
   return level;
}

VOID VIDEO_GetPortraitPalette(SDL_Color colors[256], BOOL original)
{
   SDL_Color base[256];
   int i, level = 64;
   if (!original && gpScreen != NULL)
   {
      if (VIDEO_PortraitPaletteMatches(gpScreen))
      {
         memcpy(colors, g_PortraitCurrent, sizeof(g_PortraitCurrent));
         return;
      }
      if (gpGlobals != NULL && PAL_ReadPalette(gpGlobals->wNumPalette,
          gpGlobals->fNightPalette, base))
         level = VIDEO_PortraitFadeLevel(gpScreen, base);
      if (level > 64) level = 64;
   }
   for (i = 0; i < 256; ++i)
   {
      colors[i].r = g_PortraitSource[i].r * level >> 6;
      colors[i].g = g_PortraitSource[i].g * level >> 6;
      colors[i].b = g_PortraitSource[i].b * level >> 6;
   }
}

VOID VIDEO_SetPaletteWithPortraits(SDL_Color scene[256], const SDL_Color portraits[256])
{
   memcpy(g_PortraitCurrent, portraits, sizeof(g_PortraitCurrent));
   memcpy(g_PortraitScene, scene, sizeof(g_PortraitScene));
   g_PortraitPaletteBound = TRUE;
   VIDEO_SetPalette(scene);
}

static SDL_Surface *
VIDEO_PortraitLayer(SDL_Surface *surface, BOOL create)
{
#if SDL_VERSION_ATLEAST(2,0,0)
   if (surface != NULL && surface->format->BitsPerPixel == 8)
   {
      if (surface->userdata == NULL && create)
      {
         surface->userdata = SDL_CreateRGBSurface(0, surface->w, surface->h, 32,
            0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
         if (surface->userdata == NULL)
            TerminateOnError("Cannot allocate portrait color plane");
         SDL_SetSurfaceBlendMode((SDL_Surface *)surface->userdata, SDL_BLENDMODE_NONE);
         SDL_FillRect((SDL_Surface *)surface->userdata, NULL, 0);
      }
      return (SDL_Surface *)surface->userdata;
   }
#endif
   return NULL;
}

VOID VIDEO_ClearPortraits(SDL_Surface *surface)
{
   SDL_Surface *layer = VIDEO_PortraitLayer(surface, FALSE);
   if (layer != NULL)
   {
      SDL_SetClipRect(layer, NULL);
      SDL_FillRect(layer, NULL, 0);
   }
}

INT VIDEO_FillRect(SDL_Surface *surface, const SDL_Rect *rect, Uint32 color)
{
   int result = SDL_FillRect(surface, (SDL_Rect *)rect, color);
   SDL_Surface *layer = VIDEO_PortraitLayer(surface, FALSE);
   if (result == 0 && layer != NULL)
   {
      SDL_SetClipRect(layer, &surface->clip_rect);
      SDL_FillRect(layer, (SDL_Rect *)rect, 0);
   }
   return result;
}

INT VIDEO_CopySurface(SDL_Surface *source, const SDL_Rect *src,
                      SDL_Surface *target, SDL_Rect *dst)
{
   SDL_Rect destination = {0, 0, 0, 0}, original;
   SDL_Surface *from = VIDEO_PortraitLayer(source, FALSE);
   SDL_Surface *to = VIDEO_PortraitLayer(target, from != NULL);
   int result;
   if (dst != NULL) destination = *dst;
   original = destination;
   result = SDL_BlitSurface(source, (SDL_Rect *)src, target, &destination);
   if (result == 0 && to != NULL)
   {
      SDL_SetClipRect(to, &target->clip_rect);
      if (from != NULL)
      {
         SDL_SetClipRect(from, &source->clip_rect);
         SDL_BlitSurface(from, (SDL_Rect *)src, to, &original);
      }
      else SDL_FillRect(to, &destination, 0);
   }
   if (dst != NULL) *dst = destination;
   return result;
}

VOID VIDEO_FreeSurface(SDL_Surface *surface)
{
   SDL_Surface *layer = VIDEO_PortraitLayer(surface, FALSE);
   SDL_FreeSurface(layer);
   SDL_FreeSurface(surface);
}

VOID VIDEO_SetPortrait(SDL_Surface *surface, const BYTE *pixels, int w, int h,
                       PAL_POS pos, const BYTE palette[768])
{
   SDL_Surface *layer = VIDEO_PortraitLayer(surface, TRUE);
   int x, y;
   if (layer == NULL) return; // SDL1 retains the existing indexed adaptation.
   if (!g_PortraitInitialized || memcmp(g_PortraitSourceBytes, palette, 768) != 0)
      VIDEO_InitPortraitPalette(palette);
   for (y = 0; y < h; ++y)
      for (x = 0; x < w; ++x)
      {
         int dx = PAL_X(pos) + x, dy = PAL_Y(pos) + y;
         BYTE index = pixels[y * w + x];
         if (index != 0 && dx >= 0 && dx < surface->w && dy >= 0 && dy < surface->h)
         {
            ((Uint32 *)((BYTE *)layer->pixels + dy * layer->pitch))[dx] =
               0x80000000 | index;
         }
      }
}

INT VIDEO_ComposeSurface(SDL_Surface *source, SDL_Surface *target,
                         const SDL_Color base[256])
{
   SDL_Surface *layer = VIDEO_PortraitLayer(source, FALSE);
   int level, x, y;
   BOOL bound;
   if (source->w != target->w || source->h != target->h ||
       target->format->BytesPerPixel != 4) return -1;
   if (SDL_BlitSurface(source, NULL, target, NULL) != 0) return -1;
   if (layer == NULL) return 0;
   bound = VIDEO_PortraitPaletteMatches(source);
   level = bound ? 64 : VIDEO_PortraitFadeLevel(source, base);
   for (y = 0; y < source->h; ++y)
      for (x = 0; x < source->w; ++x)
      {
         Uint32 color = ((Uint32 *)((BYTE *)layer->pixels + y * layer->pitch))[x];
         if ((color >> 24) == 0xFF) // Already composed transition RGB.
            ((Uint32 *)((BYTE *)target->pixels + y * target->pitch))[x] =
               SDL_MapRGBA(target->format, (color >> 16) & 255,
                  (color >> 8) & 255, color & 255, 255);
         else if ((color >> 24) == 0x80 && level <= 64)
         {
            SDL_Color c = bound ? g_PortraitCurrent[color & 255] : g_PortraitSource[color & 255];
            ((Uint32 *)((BYTE *)target->pixels + y * target->pitch))[x] =
               SDL_MapRGBA(target->format, c.r * level >> 6, c.g * level >> 6,
                  c.b * level >> 6, 255);
         }
      }
   return 0;
}

static SDL_Surface *VIDEO_DisplaySurface(SDL_Surface *source)
{
#if SDL_VERSION_ATLEAST(2,0,0)
   if (VIDEO_PortraitLayer(source, FALSE) != NULL)
   {
      SDL_Color base[256];
      if (gpPortraitComposite == NULL ||
          gpPortraitComposite->w != source->w || gpPortraitComposite->h != source->h)
      {
         SDL_FreeSurface(gpPortraitComposite);
         gpPortraitComposite = SDL_CreateRGBSurface(0, source->w, source->h, 32,
            0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);
         if (gpPortraitComposite == NULL)
            TerminateOnError("Cannot allocate portrait composite");
         SDL_SetSurfaceBlendMode(gpPortraitComposite, SDL_BLENDMODE_NONE);
      }
      if (PAL_ReadPalette(gpGlobals->wNumPalette, gpGlobals->fNightPalette, base) &&
          VIDEO_ComposeSurface(source, gpPortraitComposite, base) == 0)
         return gpPortraitComposite;
   }
#endif
   return source;
}

VOID VIDEO_ShiftPortraitRow(SDL_Surface *surface, int row, int shift)
{
   SDL_Surface *layer = VIDEO_PortraitLayer(surface, FALSE);
   Uint32 saved[320], *pixels;
   if (layer == NULL || surface->w != 320 || row < 0 || row >= surface->h) return;
   shift %= 320;
   if (shift <= 0) return;
   pixels = (Uint32 *)((BYTE *)layer->pixels + row * layer->pitch);
   memcpy(saved, pixels, shift * sizeof(Uint32));
   memmove(pixels, pixels + shift, (320 - shift) * sizeof(Uint32));
   memcpy(pixels + 320 - shift, saved, shift * sizeof(Uint32));
}

struct tagPORTRAITTRANSITION
{
   SDL_Surface *source, *target, *before, *after;
   BYTE *mask;
};

PORTRAITTRANSITION *VIDEO_BeginPortraitTransition(SDL_Surface *source, SDL_Surface *target)
{
   SDL_Surface *from = VIDEO_PortraitLayer(source, FALSE);
   SDL_Surface *to = VIDEO_PortraitLayer(target, FALSE);
   PORTRAITTRANSITION *transition;
   SDL_Color base[256];
   int x, y;
   if (from == NULL && to == NULL) return NULL;
   if (source->w != target->w || source->h != target->h)
      TerminateOnError("Portrait transition dimensions differ");
   transition = (PORTRAITTRANSITION *)UTIL_calloc(1, sizeof(*transition));
   transition->source = source;
   transition->target = target;
   transition->mask = (BYTE *)UTIL_calloc(source->w * source->h, 1);
   transition->before = SDL_CreateRGBSurface(0, source->w, source->h, 32,
      0x00FF0000, 0x0000FF00, 0x000000FF, 0);
   transition->after = SDL_CreateRGBSurface(0, source->w, source->h, 32,
      0x00FF0000, 0x0000FF00, 0x000000FF, 0);
   if (transition->before == NULL || transition->after == NULL)
      TerminateOnError("Cannot allocate portrait transition");
   if (gpGlobals->f.fpRGM != NULL)
   {
      if (!PAL_ReadPalette(gpGlobals->wNumPalette, gpGlobals->fNightPalette, base))
         TerminateOnError("Cannot read portrait transition palette");
   }
   else memcpy(base, source->format->palette->colors, sizeof(base));
   if (VIDEO_ComposeSurface(target, transition->before, base) != 0 ||
       VIDEO_ComposeSurface(source, transition->after, base) != 0)
      TerminateOnError("Cannot compose portrait transition");
   to = VIDEO_PortraitLayer(target, TRUE);
   for (y = 0; y < source->h; ++y)
      for (x = 0; x < source->w; ++x)
      {
         Uint32 *pixel = (Uint32 *)((BYTE *)to->pixels + y * to->pitch) + x;
         if (*pixel || (from != NULL &&
             ((Uint32 *)((BYTE *)from->pixels + y * from->pitch))[x]))
         {
            transition->mask[y * source->w + x] = 1;
            *pixel = 0xFF000000 |
               ((Uint32 *)((BYTE *)transition->before->pixels + y * transition->before->pitch))[x];
         }
      }
   return transition;
}

VOID VIDEO_StepPortraitTransition(PORTRAITTRANSITION *transition, int first, int stride,
                                  int step, int steps)
{
   SDL_Surface *to;
   int at, x, y;
   if (transition == NULL) return;
   to = VIDEO_PortraitLayer(transition->target, FALSE);
   for (at = first; at < transition->target->pitch * transition->target->h; at += stride)
   {
      y = at / transition->target->pitch;
      x = at % transition->target->pitch;
      if (x < transition->target->w && transition->mask[y * transition->target->w + x])
      {
         Uint32 a, b, *pixel = (Uint32 *)((BYTE *)to->pixels + y * to->pitch) + x;
         // Keep the exact RGB endpoint until the whole transition finishes.
         // Twelve PC rounds need not converge a 15-step low-nibble gap.
         a = ((Uint32 *)((BYTE *)transition->before->pixels + y * transition->before->pitch))[x];
         b = ((Uint32 *)((BYTE *)transition->after->pixels + y * transition->after->pitch))[x];
         *pixel = 0xFF000000 |
            (((((a >> 16) & 255) * (steps-step) + ((b >> 16) & 255) * step) / steps) << 16) |
            (((((a >> 8) & 255) * (steps-step) + ((b >> 8) & 255) * step) / steps) << 8) |
            (((a & 255) * (steps-step) + (b & 255) * step) / steps);
      }
   }
}

VOID VIDEO_EndPortraitTransition(PORTRAITTRANSITION *transition)
{
   SDL_Surface *from, *to;
   int x, y;
   if (transition == NULL) return;
   from = VIDEO_PortraitLayer(transition->source, FALSE);
   to = VIDEO_PortraitLayer(transition->target, FALSE);
   for (y = 0; y < transition->target->h; ++y)
      for (x = 0; x < transition->target->w; ++x)
         if (transition->mask[y * transition->target->w + x])
            ((Uint32 *)((BYTE *)to->pixels + y * to->pitch))[x] = from == NULL ? 0 :
               ((Uint32 *)((BYTE *)from->pixels + y * from->pitch))[x];
   SDL_FreeSurface(transition->before);
   SDL_FreeSurface(transition->after);
   free(transition->mask);
   free(transition);
}

#if PAL_HAS_GLSL
#include "video_glsl.h"
#endif

#if SDL_VERSION_ATLEAST(2, 0, 0)
void VIDEO_SetupTouchArea(int window_w, int window_h, int draw_w, int draw_h)
{
	gOverlayRect.x = (window_w - draw_w) / 2;
	gOverlayRect.y = (window_h - draw_h) / 2;
	gOverlayRect.w = draw_w;
	gOverlayRect.h = draw_h;
#if PAL_HAS_TOUCH
	PAL_SetTouchBounds(window_w, window_h, gOverlayRect);
#endif
}

#define SDL_SoftStretch SDL_UpperBlit
static SDL_Texture *VIDEO_CreateTexture(int width, int height)
{
	int texture_width, texture_height;
	double ratio = (double)width / (double)height;
	ratio *= 1.6f * (double)gConfig.dwTextureHeight / (float)gConfig.dwTextureWidth;
	//
	// Check whether to keep the aspect ratio
	//
	if (gConfig.fKeepAspectRatio && fabs(ratio - 1.6f) > FLT_EPSILON)
	{
		if (ratio > 1.6f)
		{
			texture_height = 200;
			texture_width = (int)(200 * ratio) & ~0x3;
			ratio = (float)height / 200.0f;
		}
		else
		{
			texture_width = 320;
			texture_height = (int)(320 / ratio) & ~0x3;
			ratio = (float)width / 320.0f;
		}

		WORD w = (WORD)(ratio * 320.0f) & ~0x3;
		WORD h = (WORD)(ratio * 200.0f) & ~0x3;
		gTextureRect.x = (texture_width - 320) / 2;
		gTextureRect.y = (texture_height - 200) / 2;
		gTextureRect.w = 320; gTextureRect.h = 200;
		
		VIDEO_SetupTouchArea(width,height,w,h);
	}
	else
	{
		texture_width = 320;
		texture_height = 200;
		gTextureRect.x = gTextureRect.y = 0;
		gTextureRect.w = 320; gTextureRect.h = 200;
		
		VIDEO_SetupTouchArea(width,height,width,height);
	}

	//
	// Create texture for screen.
	//
	return SDL_CreateTexture(gpRenderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING, texture_width, texture_height);
}
#endif

void NullFunc() {}

INT
VIDEO_Startup(
   VOID
)
/*++
  Purpose:

    Initialze the video subsystem.

  Parameters:

    None.

  Return value:

    0 = success, -1 = fail to create the screen surface,
    -2 = fail to create screen buffer.

--*/
{
	extern SDL_Surface* STBIMG_Load(const char* file);
	extern char *dirname(char *path);
#if APPIMAGE
	SDL_Surface *surf = STBIMG_Load( PAL_va(0, "%s%s", dirname(dirname(dirname(gExecutablePath))), "/usr/share/icons/hicolor/256x256/apps/sdlpal.png" ) );
#endif

#if SDL_VERSION_ATLEAST(2,0,0)
   int render_w, render_h;

   gRenderBackend.Init = NullFunc;
   gRenderBackend.Setup = NullFunc;
   gRenderBackend.CreateTexture = VIDEO_CreateTexture;
   gRenderBackend.RenderCopy = VIDEO_RenderCopy;

#if PAL_HAS_GLSL
   if( gConfig.fEnableGLSL) {
	   gRenderBackend.Init = VIDEO_GLSL_Init;
	   gRenderBackend.Setup = VIDEO_GLSL_Setup;
	   gRenderBackend.CreateTexture = VIDEO_GLSL_CreateTexture;
	   gRenderBackend.RenderCopy = VIDEO_GLSL_RenderCopy;
   }
#endif
	
   gRenderBackend.Init();

   //
   // Before we can render anything, we need a window and a renderer.
   //
   if (gpWindow == NULL)
   gpWindow = SDL_CreateWindow("Pal", SDL_WINDOWPOS_UNDEFINED, SDL_WINDOWPOS_UNDEFINED,
                               gConfig.dwScreenWidth, gConfig.dwScreenHeight, PAL_VIDEO_INIT_FLAGS | (gConfig.fFullScreen ? SDL_WINDOW_BORDERLESS : 0));

   if (gpWindow == NULL)
   {
      return -1;
   }

# if APPIMAGE
	if(surf){
		SDL_SetWindowIcon(gpWindow, surf);
	}
# endif

   gpRenderer = SDL_CreateRenderer(gpWindow, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);

   gRenderBackend.Setup();

   if (gpRenderer == NULL)
   {
      return -1;
   }

#if defined (__IOS__)
   SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 0);
   SDL_GL_SetAttribute(SDL_GL_RETAINED_BACKING, 1);
#endif

   //
   // Create the screen buffer and the backup screen buffer.
   //
   gpScreen = SDL_CreateRGBSurface(SDL_SWSURFACE, 320, 200, 8, 0, 0, 0, 0);
   gpScreenBak = SDL_CreateRGBSurface(SDL_SWSURFACE, 320, 200, 8, 0, 0, 0, 0);
   gpScreenReal = SDL_CreateRGBSurface(SDL_SWSURFACE, 320, 200, 32,
                                       0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000);

   //
   // Create texture for screen.
   //
   SDL_GetRendererOutputSize(gpRenderer, &render_w, &render_h);
   if(!gConfig.fEnableGLSL)
      SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, gConfig.pszScaleQuality);
   gpTexture = gRenderBackend.CreateTexture(render_w, render_h);
   if(gConfig.fEnableGLSL)
      SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0");

   //
   // Create palette object
   //
   gpPalette = SDL_AllocPalette(256);

   //
   // Failed?
   //
   if (gpScreen == NULL || gpScreenBak == NULL || gpScreenReal == NULL || gpTexture == NULL || gpPalette == NULL)
   {
      VIDEO_Shutdown();
      return -2;
   }

   //
   // Create texture for overlay.
   //
   if (gConfig.fUseTouchOverlay)
   {
      extern const void * PAL_LoadOverlayBMP(void);
      extern int PAL_OverlayBMPLength();

      const void *bmp = PAL_LoadOverlayBMP();
      SDL_Surface *overlay = SDL_LoadBMP_RW(SDL_RWFromConstMem(bmp, PAL_OverlayBMPLength()), 1);
      free((void*)bmp);
      if (overlay != NULL)
      {
         SDL_SetColorKey(overlay, SDL_RLEACCEL, SDL_MapRGB(overlay->format, 255, 0, 255));
         SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, gConfig.pszScaleQuality);
         gpTouchOverlay = SDL_CreateTextureFromSurface(gpRenderer, overlay);
         SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "0");
         SDL_SetTextureAlphaMod(gpTouchOverlay, 120);
         SDL_FreeSurface(overlay);
      }
   }
# if PAL_HAS_GLSL
   // notice: power of 2
#  define PIXELS 1
   // We need a total empty texture in case of not using touch overlay.
   // Or GL runtime will pick the previous texture - the main screen itself
   // and reuse it - that makes color seems overexposed
   else if( gConfig.fEnableGLSL )
   {
	   BYTE pixels[4*PIXELS*PIXELS];
	   memset(pixels, 0, sizeof(pixels));
	   SDL_Surface *temp = SDL_CreateRGBSurfaceFrom(pixels, PIXELS, PIXELS, 32, PIXELS, 0, 0, 0, 0);
	   gpTouchOverlay = SDL_CreateTextureFromSurface(gpRenderer, temp);
	   SDL_FreeSurface(temp);
   }
# endif
#else

# if APPIMAGE
	if(surf){
		SDL_WM_SetIcon(surf, NULL);
	}
# endif

   //
   // Create the screen surface.
   //
   gpScreenReal = SDL_SetVideoMode(gConfig.dwScreenWidth, gConfig.dwScreenHeight, 8, PAL_VIDEO_INIT_FLAGS);

   if (gpScreenReal == NULL)
   {
      //
      // Fall back to 640x480 software mode.
      //
      gpScreenReal = SDL_SetVideoMode(640, 480, 8,
         SDL_SWSURFACE | (gConfig.fFullScreen ? SDL_FULLSCREEN : 0));
   }

   //
   // Still fail?
   //
   if (gpScreenReal == NULL)
   {
      return -1;
   }

   gpPalette = gpScreenReal->format->palette;

   //
   // Create the screen buffer and the backup screen buffer.
   //
   gpScreen = SDL_CreateRGBSurface(gpScreenReal->flags & ~SDL_HWSURFACE, 320, 200, 8,
      gpScreenReal->format->Rmask, gpScreenReal->format->Gmask,
      gpScreenReal->format->Bmask, gpScreenReal->format->Amask);

   gpScreenBak = SDL_CreateRGBSurface(gpScreenReal->flags & ~SDL_HWSURFACE, 320, 200, 8,
      gpScreenReal->format->Rmask, gpScreenReal->format->Gmask,
      gpScreenReal->format->Bmask, gpScreenReal->format->Amask);

   //
   // Failed?
   //
   if (gpScreen == NULL || gpScreenBak == NULL)
   {
      VIDEO_Shutdown();
      return -2;
   }

   if (gConfig.fFullScreen)
   {
      SDL_ShowCursor(FALSE);
   }

#endif

#if APPIMAGE
	if(surf)
		SDL_FreeSurface(surf);
#endif

   return 0;
}

VOID
VIDEO_Shutdown(
   VOID
)
/*++
  Purpose:

    Shutdown the video subsystem.

  Parameters:

    None.

  Return value:

    None.

--*/
{
#if PAL_HAS_GLSL
    // since gConfig is cleared already we'd to detect on side effects
	if( gRenderBackend.Init == VIDEO_GLSL_Init ) {
		VIDEO_GLSL_Destroy();
	}
#endif

   if (gpScreen != NULL)
   {
      VIDEO_FreeSurface(gpScreen);
   }
   gpScreen = NULL;

   if (gpScreenBak != NULL)
   {
      VIDEO_FreeSurface(gpScreenBak);
   }
   gpScreenBak = NULL;
   SDL_FreeSurface(gpPortraitComposite);
   gpPortraitComposite = NULL;

#if SDL_VERSION_ATLEAST(2,0,0)

   if (gpTouchOverlay)
   {
      SDL_DestroyTexture(gpTouchOverlay);
   }
   gpTouchOverlay = NULL;

   if (gpTexture)
   {
	  SDL_DestroyTexture(gpTexture);
   }
   gpTexture = NULL;

   if (gpRenderer)
   {
      SDL_DestroyRenderer(gpRenderer);
   }
   gpRenderer = NULL;

   if (gpWindow)
   {
      SDL_DestroyWindow(gpWindow);
   }
   gpWindow = NULL;

   if (gpPalette)
   {
      SDL_FreePalette(gpPalette);
   }
#endif
   gpPalette = NULL;

   if (gpScreenReal != NULL)
   {
      SDL_FreeSurface(gpScreenReal);
   }
   gpScreenReal = NULL;
}

#if SDL_VERSION_ATLEAST(2,0,0)
VOID
VIDEO_RenderCopy(
   VOID
)
{
	void *texture_pixels;
	int texture_pitch;

	SDL_LockTexture(gpTexture, NULL, &texture_pixels, &texture_pitch);
	memset(texture_pixels, 0, gTextureRect.y * texture_pitch);
	uint8_t *pixels = (uint8_t *)texture_pixels + gTextureRect.y * texture_pitch;
	uint8_t *src = (uint8_t *)gpScreenReal->pixels;
	int left_pitch = gTextureRect.x << 2;
	int right_pitch = texture_pitch - ((gTextureRect.x + gTextureRect.w) << 2);
	for (int y = 0; y < gTextureRect.h; y++, src += gpScreenReal->pitch)
	{
		memset(pixels, 0, left_pitch); pixels += left_pitch;
		memcpy(pixels, src, 320 << 2); pixels += 320 << 2;
		memset(pixels, 0, right_pitch); pixels += right_pitch;
	}
	memset(pixels, 0, gTextureRect.y * texture_pitch);
	SDL_UnlockTexture(gpTexture);

	SDL_RenderClear(gpRenderer);
	SDL_RenderCopy(gpRenderer, gpTexture, NULL, NULL);
	if (gConfig.fUseTouchOverlay)
	{
		SDL_RenderCopy(gpRenderer, gpTouchOverlay, NULL, &gOverlayRect);
	}
#ifdef UNIT_TEST
	if (VIDEO_TestFrameHook != NULL) VIDEO_TestFrameHook();
#endif
	SDL_RenderPresent(gpRenderer);
}
#endif

VOID
VIDEO_UpdateScreen(
   const SDL_Rect  *lpRect
)
/*++
  Purpose:

    Update the screen area specified by lpRect.

  Parameters:

    [IN]  lpRect - Screen area to update.

  Return value:

    None.

--*/
{
   SDL_Rect        srcrect, dstrect;
   short           offset = 240 - 200;
   short           screenRealHeight = gpScreenReal->h;
   short           screenRealY = 0;

#if SDL_VERSION_ATLEAST(2,0,0)
   if (g_bRenderPaused)
   {
	   return;
   }
#endif

   //
   // Lock surface if needed
   //
   if (SDL_MUSTLOCK(gpScreenReal))
   {
      if (SDL_LockSurface(gpScreenReal) < 0)
         return;
   }

   if (!bScaleScreen)
   {
      screenRealHeight -= offset;
      screenRealY = offset / 2;
   }

   if (lpRect != NULL)
   {
      dstrect.x = (SHORT)((INT)(lpRect->x) * gpScreenReal->w / gpScreen->w);
      dstrect.y = (SHORT)((INT)(screenRealY + lpRect->y) * screenRealHeight / gpScreen->h);
      dstrect.w = (WORD)((DWORD)(lpRect->w) * gpScreenReal->w / gpScreen->w);
      dstrect.h = (WORD)((DWORD)(lpRect->h) * screenRealHeight / gpScreen->h);

      SDL_SoftStretch(VIDEO_DisplaySurface(gpScreen), (SDL_Rect *)lpRect, gpScreenReal, &dstrect);
   }
   else if (g_wShakeTime != 0)
   {
      const int shakeHeight = g_wShakeLevel * screenRealHeight / gpScreen->h;
      //
      // Shake the screen
      //
      srcrect.x = 0;
      srcrect.y = 0;
      srcrect.w = 320;
      srcrect.h = 200 - g_wShakeLevel;

      dstrect.x = 0;
      dstrect.y = screenRealY;
      dstrect.w = 320 * gpScreenReal->w / gpScreen->w;
      dstrect.h = screenRealHeight - shakeHeight;

      if (g_wShakeTime & 1)
      {
         srcrect.y = g_wShakeLevel;
      }
      else
      {
         dstrect.y = screenRealY + shakeHeight;
      }

      SDL_SoftStretch(VIDEO_DisplaySurface(gpScreen), &srcrect, gpScreenReal, &dstrect);

      if (g_wShakeTime & 1)
      {
         dstrect.y = screenRealY + screenRealHeight - shakeHeight;
      }
      else
      {
         dstrect.y = screenRealY;
      }

      dstrect.h = shakeHeight;

      SDL_FillRect(gpScreenReal, &dstrect, 0);

#if SDL_MAJOR_VERSION == 1 && SDL_MINOR_VERSION <= 2
      dstrect.x = dstrect.y = 0;
      dstrect.w = gpScreenReal->w;
      dstrect.h = gpScreenReal->h;
#endif
      g_wShakeTime--;
   }
   else
   {
      dstrect.x = 0;
      dstrect.y = screenRealY;
      dstrect.w = gpScreenReal->w;
      dstrect.h = screenRealHeight;

      SDL_SoftStretch(VIDEO_DisplaySurface(gpScreen), NULL, gpScreenReal, &dstrect);

#if SDL_MAJOR_VERSION == 1 && SDL_MINOR_VERSION <= 2
      dstrect.x = dstrect.y = 0;
      dstrect.w = gpScreenReal->w;
      dstrect.h = gpScreenReal->h;
#endif
   }

#if SDL_VERSION_ATLEAST(2,0,0)
   gRenderBackend.RenderCopy();
#else
   SDL_UpdateRect(gpScreenReal, dstrect.x, dstrect.y, dstrect.w, dstrect.h);
#ifdef UNIT_TEST
   if (VIDEO_TestFrameHook) VIDEO_TestFrameHook();
#endif
#endif

   if (SDL_MUSTLOCK(gpScreenReal))
   {
	   SDL_UnlockSurface(gpScreenReal);
   }
}

VOID
VIDEO_SetPalette(
   SDL_Color        rgPalette[256]
)
/*++
  Purpose:

    Set the palette of the screen.

  Parameters:

    [IN]  rgPalette - array of 256 colors.

  Return value:

    None.

--*/
{
#if SDL_VERSION_ATLEAST(2,0,0)
   SDL_Rect rect;

   SDL_SetPaletteColors(gpPalette, rgPalette, 0, 256);

   SDL_SetSurfacePalette(gpScreen, gpPalette);
   SDL_SetSurfacePalette(gpScreenBak, gpPalette);

   //
   // HACKHACK: need to invalidate gpScreen->map otherwise the palette
   // would not be effective during blit
   //
   SDL_SetSurfaceColorMod(gpScreen, 0, 0, 0);
   SDL_SetSurfaceColorMod(gpScreen, 0xFF, 0xFF, 0xFF);
   SDL_SetSurfaceColorMod(gpScreenBak, 0, 0, 0);
   SDL_SetSurfaceColorMod(gpScreenBak, 0xFF, 0xFF, 0xFF);

   rect.x = 0;
   rect.y = 0;
   rect.w = 320;
   rect.h = 200;

   VIDEO_UpdateScreen(&rect);
#else
   SDL_SetPalette(gpScreen, SDL_LOGPAL | SDL_PHYSPAL, rgPalette, 0, 256);
   SDL_SetPalette(gpScreenBak, SDL_LOGPAL | SDL_PHYSPAL, rgPalette, 0, 256);
   SDL_SetPalette(gpScreenReal, SDL_LOGPAL | SDL_PHYSPAL, rgPalette, 0, 256);
#ifdef UNIT_TEST
   if (!g_bRenderPaused && VIDEO_TestFrameHook) VIDEO_TestFrameHook();
#endif
# if defined(PAL_FORCE_UPDATE_ON_PALETTE_SET)
   {
      static UINT32 time = 0;
      if (SDL_GetTicks() - time > 50)
      {
	      SDL_UpdateRect(gpScreenReal, 0, 0, gpScreenReal->w, gpScreenReal->h);
	      time = SDL_GetTicks();
      }
   }
# endif
#endif
}

VOID
VIDEO_Resize(
   INT             w,
   INT             h
)
/*++
  Purpose:

    This function is called when user resized the window.

  Parameters:

    [IN]  w - width of the window after resizing.

    [IN]  h - height of the window after resizing.

  Return value:

    None.

--*/
{
#if SDL_VERSION_ATLEAST(2,0,0)
   SDL_Rect rect;

   if (gpTexture)
   {
      SDL_DestroyTexture(gpTexture);
   }

   gpTexture = gRenderBackend.CreateTexture(w, h);

   if (gpTexture == NULL)
   {
      TerminateOnError("Re-creating texture failed on window resize!\n");
   }

   rect.x = 0;
   rect.y = 0;
   rect.w = 320;
   rect.h = 200;

   VIDEO_UpdateScreen(&rect);
#else
   DWORD                    flags;
   PAL_LARGE SDL_Color      palette[256];
   int                      i, bpp;

   //
   // Get the original palette.
   //
   if (gpScreenReal->format->palette != NULL)
   {
      for (i = 0; i < gpScreenReal->format->palette->ncolors; i++)
      {
         palette[i] = gpScreenReal->format->palette->colors[i];
      }
   }
   else i = 0;

   //
   // Create the screen surface.
   //
   flags = gpScreenReal->flags;
   bpp = gpScreenReal->format->BitsPerPixel;

   SDL_FreeSurface(gpScreenReal);
   gpScreenReal = SDL_SetVideoMode(w, h, bpp, flags);

   if (gpScreenReal == NULL)
   {
      //
      // Fall back to software windowed mode in default size.
      //
      gpScreenReal = SDL_SetVideoMode(PAL_DEFAULT_WINDOW_WIDTH, PAL_DEFAULT_WINDOW_HEIGHT, bpp, SDL_SWSURFACE);
   }

   SDL_SetPalette(gpScreenReal, SDL_PHYSPAL | SDL_LOGPAL, palette, 0, i);
   VIDEO_UpdateScreen(NULL);

   gpPalette = gpScreenReal->format->palette;
#endif
}

SDL_Color *
VIDEO_GetPalette(
   VOID
)
/*++
  Purpose:

    Get the current palette of the screen.

  Parameters:

    None.

  Return value:

    Pointer to the current palette.

--*/
{
   return gpPalette->colors;
}

VOID
VIDEO_ToggleScaleScreen(
   VOID
)
/*++
  Purpose:

    Toggle scalescreen mode, only used in some platforms.

  Parameters:

    None.

  Return value:

    None.

--*/
{
   bScaleScreen = !bScaleScreen;
   VIDEO_Resize(PAL_DEFAULT_WINDOW_WIDTH, PAL_DEFAULT_WINDOW_HEIGHT);
   VIDEO_UpdateScreen(NULL);
}

VOID
VIDEO_ToggleFullscreen(
   VOID
)
/*++
  Purpose:

    Toggle fullscreen mode.

  Parameters:

    None.

  Return value:

    None.

--*/
{
#if SDL_VERSION_ATLEAST(2,0,0)
	if (gConfig.fFullScreen)
	{
		SDL_SetWindowFullscreen(gpWindow, 0);
		gConfig.fFullScreen = FALSE;
	}
	else
	{
		SDL_SetWindowFullscreen(gpWindow, SDL_WINDOW_FULLSCREEN_DESKTOP);
		gConfig.fFullScreen = TRUE;
	}
#else
   DWORD                    flags;
   PAL_LARGE SDL_Color      palette[256];
   int                      i, bpp;

   //
   // Get the original palette.
   //
   if (gpScreenReal->format->palette != NULL)
   {
      for (i = 0; i < gpScreenReal->format->palette->ncolors; i++)
      {
         palette[i] = gpScreenReal->format->palette->colors[i];
      }
   }

   //
   // Get the flags and bpp of the original screen surface
   //
   flags = gpScreenReal->flags;
   bpp = gpScreenReal->format->BitsPerPixel;

   if (flags & SDL_FULLSCREEN)
   {
      //
      // Already in fullscreen mode. Remove the fullscreen flag.
      //
      flags &= ~SDL_FULLSCREEN;
      flags |= SDL_RESIZABLE;
      SDL_ShowCursor(TRUE);
   }
   else
   {
      //
      // Not in fullscreen mode. Set the fullscreen flag.
      //
      flags |= SDL_FULLSCREEN;
      SDL_ShowCursor(FALSE);
   }

   //
   // Free the original screen surface
   //
   SDL_FreeSurface(gpScreenReal);

   //
   // ... and create a new one
   //
   if (gConfig.dwScreenWidth == 640 && gConfig.dwScreenHeight == 400 && (flags & SDL_FULLSCREEN))
   {
      gpScreenReal = SDL_SetVideoMode(640, 480, bpp, flags);
   }
   else if (gConfig.dwScreenWidth == 640 && gConfig.dwScreenHeight == 480 && !(flags & SDL_FULLSCREEN))
   {
      gpScreenReal = SDL_SetVideoMode(640, 400, bpp, flags);
   }
   else
   {
      gpScreenReal = SDL_SetVideoMode(gConfig.dwScreenWidth, gConfig.dwScreenHeight, bpp, flags);
   }

   VIDEO_SetPalette(palette);

   //
   // Update the screen
   //
   VIDEO_UpdateScreen(NULL);
#endif
}

VOID
VIDEO_ChangeDepth(
   INT             bpp
)
/*++
  Purpose:

    Change screen color depth.

  Parameters:

    [IN]  bpp - bits per pixel (0 = default).

  Return value:

    None.

--*/
{
#if !SDL_VERSION_ATLEAST(2,0,0)
   DWORD                    flags;
   int                      w, h;

   //
   // Get the flags and resolution of the original screen surface
   //
   flags = gpScreenReal->flags;
   w = gpScreenReal->w;
   h = gpScreenReal->h;

   //
   // Clear the screen surface.
   //
   SDL_FillRect(gpScreenReal, NULL, 0);

   //
   // Create the screen surface.
   //
   SDL_FreeSurface(gpScreenReal);
   gpScreenReal = SDL_SetVideoMode(w, h, (bpp == 0)?8:bpp, flags);

   if (gpScreenReal == NULL)
   {
      //
      // Fall back to software windowed mode in default size.
      //
      gpScreenReal = SDL_SetVideoMode(PAL_DEFAULT_WINDOW_WIDTH, PAL_DEFAULT_WINDOW_HEIGHT, (bpp == 0)?8:bpp, SDL_SWSURFACE);
   }

   gpPalette = gpScreenReal->format->palette;
#endif
}

VOID
VIDEO_SaveScreenshot(
   VOID
)
/*++
  Purpose:

    Save the screenshot of current screen to a BMP file.

  Parameters:

    None.

  Return value:

    None.

--*/
{
	char filename[32];
#ifdef _WIN32
	SYSTEMTIME st;
	GetLocalTime(&st);
	sprintf(filename, "%04d%02d%02d%02d%02d%02d%03d.bmp", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, st.wMilliseconds);
#elif !defined( GEKKO )
	struct timeval tv;
	struct tm *ptm;
	gettimeofday(&tv, NULL);
	ptm = localtime(&tv.tv_sec);
	sprintf(filename, "%04d%02d%02d%02d%02d%02d%03d.bmp", ptm->tm_year + 1900, ptm->tm_mon, ptm->tm_mday, ptm->tm_hour, ptm->tm_min, ptm->tm_sec, (int)(tv.tv_usec / 1000));
#endif

	//
	// Save the screenshot.
	//
#if SDL_VERSION_ATLEAST(2,0,0)
	SDL_SaveBMP(VIDEO_DisplaySurface(gpScreen), PAL_CombinePath(0, gConfig.pszSavePath, filename));
#else
	SDL_SaveBMP(gpScreenReal, PAL_CombinePath(0, gConfig.pszSavePath, filename));
#endif
}

VOID
VIDEO_ShakeScreen(
   WORD           wShakeTime,
   WORD           wShakeLevel
)
/*++
  Purpose:

    Set the screen shake time and level.

  Parameters:

    [IN]  wShakeTime - how many times should we shake the screen.

    [IN]  wShakeLevel - level of shaking.

  Return value:

    None.

--*/
{
   g_wShakeTime = wShakeTime;
   g_wShakeLevel = wShakeLevel;
}

VOID
VIDEO_SwitchScreen(
   WORD           wSpeed
)
/*++
  Purpose:

    Switch the screen from the backup screen buffer to the current screen buffer.
    NOTE: This will destroy the backup buffer.

  Parameters:

    [IN]  wSpeed - speed of fading (the larger value, the slower).

  Return value:

    None.

--*/
{
   int               i, j;
   const int         rgIndex[6] = {0, 3, 1, 5, 2, 4};
   SDL_Rect          dstrect;
   PORTRAITTRANSITION *portrait;

   short             offset = 240 - 200;
   short             screenRealHeight = gpScreenReal->h;
   short             screenRealY = 0;

   if (!bScaleScreen)
   {
      screenRealHeight -= offset;
      screenRealY = offset / 2;
   }

   wSpeed++;
   wSpeed *= 10;

   portrait = VIDEO_BeginPortraitTransition(gpScreen, gpScreenBak);
   for (i = 0; i < 6; i++)
   {
      for (j = rgIndex[i]; j < gpScreen->pitch * gpScreen->h; j += 6)
      {
         ((LPBYTE)(gpScreenBak->pixels))[j] = ((LPBYTE)(gpScreen->pixels))[j];
      }

      VIDEO_StepPortraitTransition(portrait, rgIndex[i], 6, 1, 1);

      //
      // Draw the backup buffer to the screen
      //
      dstrect.x = 0;
      dstrect.y = screenRealY;
      dstrect.w = gpScreenReal->w;
      dstrect.h = screenRealHeight;

	  if (SDL_MUSTLOCK(gpScreenReal))
	  {
		  if (SDL_LockSurface(gpScreenReal) < 0)
			  { VIDEO_EndPortraitTransition(portrait); return; }
	  }

      SDL_SoftStretch(VIDEO_DisplaySurface(gpScreenBak), NULL, gpScreenReal, &dstrect);
#if SDL_VERSION_ATLEAST(2, 0, 0)
      gRenderBackend.RenderCopy();
#else
      SDL_UpdateRect(gpScreenReal, 0, 0, gpScreenReal->w, gpScreenReal->h);
#ifdef UNIT_TEST
      if (VIDEO_TestFrameHook) VIDEO_TestFrameHook();
#endif
#endif

	  if (SDL_MUSTLOCK(gpScreenReal))
	  {
		  SDL_UnlockSurface(gpScreenReal);
	  }

      UTIL_Delay(wSpeed);
   }
   VIDEO_EndPortraitTransition(portrait);
   VIDEO_CopyEntireSurface(gpScreen, gpScreenBak);
   VIDEO_UpdateScreen(NULL);
}

VOID
VIDEO_FadeScreen(
   WORD           wSpeed
)
/*++
  Purpose:

    Fade from the backup screen buffer to the current screen buffer.
    NOTE: This will destroy the backup buffer.

  Parameters:

    [IN]  wSpeed - speed of fading (the larger value, the slower).

  Return value:

    None.

--*/
{
   int               i, j, k;
   DWORD             time;
   BYTE              a, b;
   const int         rgIndex[6] = {0, 3, 1, 5, 2, 4};
   SDL_Rect          dstrect;
   PORTRAITTRANSITION *portrait;
   short             offset = 240 - 200;
   short             screenRealHeight = gpScreenReal->h;
   short             screenRealY = 0;

   //
   // Lock surface if needed
   //
   if (SDL_MUSTLOCK(gpScreenReal))
   {
      if (SDL_LockSurface(gpScreenReal) < 0)
         return;
   }

   if (!bScaleScreen)
   {
      screenRealHeight -= offset;
      screenRealY = offset / 2;
   }

   time = SDL_GetTicks();

   portrait = VIDEO_BeginPortraitTransition(gpScreen, gpScreenBak);
   wSpeed++;
   wSpeed *= 10;

   for (i = 0; i < 12; i++)
   {
      for (j = 0; j < 6; j++)
      {
         PAL_ProcessEvent();
         while (!SDL_TICKS_PASSED(SDL_GetTicks(), time))
         {
            PAL_ProcessEvent();
            SDL_Delay(5);
         }
         time = SDL_GetTicks() + wSpeed;

         //
         // Blend the pixels in the 2 buffers, and put the result into the
         // backup buffer
         //
         for (k = rgIndex[j]; k < gpScreen->pitch * gpScreen->h; k += 6)
         {
            a = ((LPBYTE)(gpScreen->pixels))[k];
            b = ((LPBYTE)(gpScreenBak->pixels))[k];

            if (i > 0)
            {
               if ((a & 0x0F) > (b & 0x0F))
               {
                  b++;
               }
               else if ((a & 0x0F) < (b & 0x0F))
               {
                  b--;
               }
            }

            ((LPBYTE)(gpScreenBak->pixels))[k] = ((a & 0xF0) | (b & 0x0F));
         }

         VIDEO_StepPortraitTransition(portrait, rgIndex[j], 6, i + 1, 12);

         //
         // Draw the backup buffer to the screen
         //
         if (g_wShakeTime != 0)
         {
            const int shakeHeight = g_wShakeLevel * screenRealHeight / gpScreen->h;
            //
            // Shake the screen
            //
            SDL_Rect srcrect, dstrect;

            srcrect.x = 0;
            srcrect.y = 0;
            srcrect.w = 320;
            srcrect.h = 200 - g_wShakeLevel;

            dstrect.x = 0;
            dstrect.y = screenRealY;
            dstrect.w = 320 * gpScreenReal->w / gpScreen->w;
            dstrect.h = screenRealHeight - shakeHeight;

            if (g_wShakeTime & 1)
            {
               srcrect.y = g_wShakeLevel;
            }
            else
            {
               dstrect.y = screenRealY + shakeHeight;
            }

            SDL_SoftStretch(VIDEO_DisplaySurface(gpScreenBak), &srcrect, gpScreenReal, &dstrect);

            if (g_wShakeTime & 1)
            {
               dstrect.y = screenRealY + screenRealHeight - shakeHeight;
            }
            else
            {
               dstrect.y = screenRealY;
            }

            dstrect.h = shakeHeight;

            SDL_FillRect(gpScreenReal, &dstrect, 0);
#if SDL_VERSION_ATLEAST(2, 0, 0)
            gRenderBackend.RenderCopy();
#else
			SDL_UpdateRect(gpScreenReal, 0, 0, gpScreenReal->w, gpScreenReal->h);
#ifdef UNIT_TEST
            if (VIDEO_TestFrameHook) VIDEO_TestFrameHook();
#endif
#endif
            g_wShakeTime--;
         }
         else
         {
            dstrect.x = 0;
            dstrect.y = screenRealY;
            dstrect.w = gpScreenReal->w;
            dstrect.h = screenRealHeight;

            SDL_SoftStretch(VIDEO_DisplaySurface(gpScreenBak), NULL, gpScreenReal, &dstrect);
#if SDL_VERSION_ATLEAST(2, 0, 0)
            gRenderBackend.RenderCopy();
#else
            SDL_UpdateRect(gpScreenReal, 0, 0, gpScreenReal->w, gpScreenReal->h);
#ifdef UNIT_TEST
            if (VIDEO_TestFrameHook) VIDEO_TestFrameHook();
#endif
#endif
         }
      }
   }

   if (SDL_MUSTLOCK(gpScreenReal))
   {
      SDL_UnlockSurface(gpScreenReal);
   }

   VIDEO_EndPortraitTransition(portrait);

   //
   // Draw the result buffer to the screen as the final step
   //
   VIDEO_UpdateScreen(NULL);
}

void
VIDEO_SetWindowTitle(
	const char*     pszTitle
)
/*++
  Purpose:

    Set the caption of the window.

  Parameters:

    [IN]  pszTitle - the new caption of the window.

  Return value:

    None.

--*/
{
#if SDL_VERSION_ATLEAST(2,0,0)
	SDL_SetWindowTitle(gpWindow, PAL_CONVERT_UTF8(pszTitle));
#else
	SDL_WM_SetCaption(pszTitle, NULL);
#endif
}

SDL_Surface *
VIDEO_CreateCompatibleSurface(
	SDL_Surface    *pSource
)
{
	return VIDEO_CreateCompatibleSizedSurface(pSource, NULL);
}

SDL_Surface *
VIDEO_CreateCompatibleSizedSurface(
	SDL_Surface    *pSource,
	const SDL_Rect *pSize
)
/*++
  Purpose:

    Create a surface that compatible with the source surface.

  Parameters:

    [IN]  pSource   - the source surface from which attributes are taken.
    [IN]  pSize     - the size (width & height) of the created surface.

  Return value:

    None.

--*/
{
	//
	// Create the surface
	//
	SDL_Surface *dest = SDL_CreateRGBSurface(pSource->flags,
		pSize ? pSize->w : pSource->w,
		pSize ? pSize->h : pSource->h,
		pSource->format->BitsPerPixel,
		pSource->format->Rmask, pSource->format->Gmask,
		pSource->format->Bmask, pSource->format->Amask);

	if (dest)
	{
		VIDEO_UpdateSurfacePalette(dest);
	}

	return dest;
}

SDL_Surface *
VIDEO_DuplicateSurface(
	SDL_Surface    *pSource,
	const SDL_Rect *pRect
)
/*++
  Purpose:

    Duplicate the selected area from the source surface into new surface.

  Parameters:

    [IN]  pSource - the source surface.
	[IN]  pRect   - the area to be duplicated, NULL for entire surface.

  Return value:

    None.

--*/
{
	SDL_Surface* dest = VIDEO_CreateCompatibleSizedSurface(pSource, pRect);

	if (dest)
	{
		VIDEO_CopySurface(pSource, pRect, dest, NULL);
	}

	return dest;
}

void
VIDEO_UpdateSurfacePalette(
	SDL_Surface    *pSurface
)
/*++
  Purpose:

    Use the global palette to update the palette of pSurface.

  Parameters:

    [IN]  pSurface - the surface whose palette should be updated.

  Return value:

    None.

--*/
{
#if SDL_VERSION_ATLEAST(2, 0, 0)
	SDL_SetSurfacePalette(pSurface, gpPalette);
#else
	if (gpPalette != NULL)
	{
		SDL_SetPalette(pSurface, SDL_PHYSPAL | SDL_LOGPAL, gpPalette->colors, 0, 256);
	}
#endif
}

VOID
VIDEO_DrawSurfaceToScreen(
    SDL_Surface    *pSurface
)
/*++
  Purpose:

    Draw a surface directly to screen.

  Parameters:

    [IN]  pSurface - the surface which needs to be drawn to screen.

  Return value:

    None.

--*/
{
#if SDL_VERSION_ATLEAST(2, 0, 0)
   //
   // Draw the surface to screen.
   //
   if (g_bRenderPaused)
   {
      return;
   }
   SDL_BlitScaled(pSurface, NULL, gpScreenReal, NULL);
   gRenderBackend.RenderCopy();
#else
   SDL_Surface   *pCompatSurface;
   SDL_Rect       rect;

   rect.x = rect.y = 0;
   rect.w = pSurface->w;
   rect.h = pSurface->h;

   pCompatSurface = VIDEO_CreateCompatibleSizedSurface(gpScreenReal, &rect);

   //
   // First convert the surface to compatible format.
   //
   SDL_BlitSurface(pSurface, NULL, pCompatSurface, NULL);

   //
   // Draw the surface to screen.
   //
   SDL_SoftStretch(pCompatSurface, NULL, gpScreenReal, NULL);

   SDL_UpdateRect(gpScreenReal, 0, 0, gpScreenReal->w, gpScreenReal->h);
   SDL_FreeSurface(pCompatSurface);
#endif
}
