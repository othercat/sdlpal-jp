// Neutral nearest-neighbour shader for backend evidence, not a game filter.
#if __VERSION__ >= 130
#define ATTRIBUTE in
#define TEXTURE texture
#ifdef VERTEX
#define VARYING out
#else
#define VARYING in
out vec4 FragColor;
#endif
#else
#define ATTRIBUTE attribute
#define TEXTURE texture2D
#define VARYING varying
#define FragColor gl_FragColor
#endif
#ifdef VERTEX
uniform mat4 MVPMatrix;
ATTRIBUTE vec4 VertexCoord;
ATTRIBUTE vec4 TexCoord;
VARYING vec2 coords;
void main() {
    gl_Position = MVPMatrix * VertexCoord;
    coords = TexCoord.xy;
}
#elif defined(FRAGMENT)
uniform sampler2D Texture;
VARYING vec2 coords;
void main() {
    FragColor = TEXTURE(Texture, coords);
}
#endif
