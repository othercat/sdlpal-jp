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

#ifndef VIDEO_H
#define VIDEO_H

#include "palcommon.h"

#define VIDEO_CopyEntireSurface(s, t)   VIDEO_CopySurface((s), NULL, (t), NULL)
#define VIDEO_BackupScreen(s)           VIDEO_CopyEntireSurface((s), gpScreenBak)
#define VIDEO_RestoreScreen(t)          VIDEO_CopyEntireSurface(gpScreenBak, (t))

PAL_C_LINKAGE_BEGIN

extern SDL_Surface *gpScreen;
extern SDL_Surface *gpScreenBak;
extern volatile BOOL g_bRenderPaused;

// SDL2 engine-owned indexed surfaces reserve userdata for an optional portrait
// color plane. Ordinary drawing invalidates coverage even when the index is equal.
PAL_FORCE_INLINE VOID VIDEO_InvalidatePortraitPixel(SDL_Surface *surface, int x, int y)
{
#if SDL_VERSION_ATLEAST(2,0,0)
   if (surface->userdata != NULL && x >= 0 && x < surface->w && y >= 0 && y < surface->h)
   {
      SDL_Surface *layer = (SDL_Surface *)surface->userdata;
      ((Uint32 *)((BYTE *)layer->pixels + y * layer->pitch))[x] = 0;
   }
#endif
}

INT VIDEO_CopySurface(SDL_Surface *source, const SDL_Rect *src,
                      SDL_Surface *target, SDL_Rect *dst);
INT VIDEO_FillRect(SDL_Surface *surface, const SDL_Rect *rect, Uint32 color);
VOID VIDEO_FreeSurface(SDL_Surface *surface);
VOID VIDEO_ClearPortraits(SDL_Surface *surface);
VOID VIDEO_SetPortrait(SDL_Surface *surface, const BYTE *pixels, int w, int h,
                       PAL_POS pos, const BYTE palette[768]);
VOID VIDEO_InitPortraitPalette(const BYTE palette[768]);
VOID VIDEO_GetPortraitPalette(SDL_Color colors[256], BOOL original);
VOID VIDEO_SetPaletteWithPortraits(SDL_Color scene[256], const SDL_Color portraits[256]);
VOID VIDEO_ShiftPortraitRow(SDL_Surface *surface, int row, int shift);
typedef struct tagPORTRAITTRANSITION PORTRAITTRANSITION;
PORTRAITTRANSITION *VIDEO_BeginPortraitTransition(SDL_Surface *source, SDL_Surface *target);
VOID VIDEO_StepPortraitTransition(PORTRAITTRANSITION *transition, int first, int stride,
                                  int step, int steps);
VOID VIDEO_EndPortraitTransition(PORTRAITTRANSITION *transition);
// Convert a complete logical frame, including independent portrait colors.
// Unknown nonuniform palette effects deliberately use the indexed fallback.
INT VIDEO_ComposeSurface(SDL_Surface *source, SDL_Surface *target,
                         const SDL_Color base[256]);

#if PAL_HAS_GLSL
void Filter_StepParamSlot(int step);
void Filter_StepCurrentParam(int step);
#endif

INT
VIDEO_Startup(
   VOID
);

VOID
VIDEO_Shutdown(
   VOID
);

VOID
VIDEO_UpdateScreen(
   const SDL_Rect  *lpRect
);

VOID
VIDEO_SetPalette(
   SDL_Color        rgPalette[256]
);

VOID
VIDEO_Resize(
   INT             w,
   INT             h
);

SDL_Color *
VIDEO_GetPalette(
   VOID
);

VOID
VIDEO_ToggleFullscreen(
   VOID
);

VOID
VIDEO_ChangeDepth(
   INT             bpp
);

VOID
VIDEO_SaveScreenshot(
   VOID
);

VOID
VIDEO_ShakeScreen(
   WORD           wShakeTime,
   WORD           wShakeLevel
);

VOID
VIDEO_SwitchScreen(
   WORD           wSpeed
);

VOID
VIDEO_FadeScreen(
   WORD           wSpeed
);

void
VIDEO_SetWindowTitle(
	const char*   pszTitle
);

SDL_Surface *
VIDEO_DuplicateSurface(
	SDL_Surface    *pSource,
	const SDL_Rect *pRect
);

SDL_Surface *
VIDEO_CreateCompatibleSurface(
	SDL_Surface    *pSource
);

SDL_Surface *
VIDEO_CreateCompatibleSizedSurface(
	SDL_Surface    *pSource,
	const SDL_Rect *pSize
);

void
VIDEO_UpdateSurfacePalette(
	SDL_Surface    *pSurface
);

VOID
VIDEO_DrawSurfaceToScreen(
    SDL_Surface    *pSurface
);

VOID
VIDEO_RenderCopy(
    VOID
);

VOID
VIDEO_SetupTouchArea(
    int window_w,
    int window_h,
    int draw_w,
    int draw_h
);

PAL_C_LINKAGE_END

#endif
